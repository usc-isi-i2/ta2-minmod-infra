from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from mms.exceptions import EnvFileValidationError, MissingEnvTemplateFileError

ROOT_DIR = Path(__file__).parent.parent
MAIN_DIR = ROOT_DIR / "main"
MAIN_DIR.mkdir(exist_ok=True, parents=True)

CFG_FILE = ROOT_DIR / "config.yml"

REPOS = [
    "ta2-minmod-dashboard",
    "ta2-minmod-kg",
    "ta2-minmod-data",
    "ta2-minmod-data-sample",
    "ta2-minmod-editor",
]


def exec(cmd: str, cwd: Path = MAIN_DIR, env: Optional[dict] = None):
    exec_env = {"PATH": os.environ["PATH"], "HOME": str(Path.home())}
    if env is not None:
        exec_env.update(env)

    try:
        subprocess.check_call(
            cmd,
            cwd=str(cwd),
            shell=True,
            env=exec_env,
        )
    except subprocess.CalledProcessError as e:
        # Raised if the command fails
        print(
            f"Command failed with exit code {e.returncode}: command {cmd} at path : {cwd}"
        )
        raise


def exec_output(cmd: str, cwd: Path = MAIN_DIR):
    try:
        result = subprocess.check_output(
            cmd,
            cwd=str(cwd),
            shell=True,
            text=True,
            env={"PATH": os.environ["PATH"], "HOME": str(Path.home())},
        )

        return result
    except subprocess.CalledProcessError as e:
        # Raised if the command fails
        print(
            f"Command failed with exit code {e.returncode}: command {cmd} at path : {cwd}"
        )
        raise


def update_repo(repo_name: str) -> bool:
    repo_dir = MAIN_DIR / repo_name

    # Clone the repo if it does not exist
    if not repo_dir.exists():
        if repo_name == "ta2-minmod-data-sample":
            exec(
                f"git clone --depth 1 https://github.com/binh-vu/{repo_name}.git",
                cwd=MAIN_DIR,
            )
        else:
            exec(
                f"git clone --depth 1 --recurse-submodules https://github.com/DARPA-CRITICALMAAS/{repo_name}.git",
                cwd=MAIN_DIR,
            )
        if repo_name == "ta2-minmod-data":
            exec(
                "git lfs install --force",
                cwd=MAIN_DIR / "ta2-minmod-data",
            )
            exec(
                f"git lfs fetch --all",
                cwd=MAIN_DIR / "ta2-minmod-data",
            )
            exec(
                f"git lfs pull",
                cwd=MAIN_DIR / "ta2-minmod-data",
            )
        return True

    # pull changes
    try:
        if repo_name == "ta2-minmod-data":
            exec(
                f"git lfs fetch --all",
                cwd=MAIN_DIR / "ta2-minmod-data",
            )
            exec(
                f"git lfs pull",
                cwd=MAIN_DIR / "ta2-minmod-data",
            )
        else:
            exec("git fetch --all", cwd=repo_dir)
            exec("git pull", cwd=repo_dir)
            # a pull can move a submodule pin; this is what checks the new one out
            exec("git submodule update --init --recursive", cwd=repo_dir)

        return True  # Repository updated
    except subprocess.CalledProcessError as e:
        print(f"Error during 'git pull': {e}")
        # retry with clean
        try:
            exec("git clean -fd", cwd=repo_dir)
            exec("git pull", cwd=repo_dir)
            exec("git submodule update --init --recursive", cwd=repo_dir)
            return True
        except subprocess.CalledProcessError as retry_error:
            print(f"Error during retry 'git pull': {retry_error}")
            return False


def read_env_vars(envfile_path: Path) -> list[str]:

    env_vars = []

    if envfile_path.exists():
        with open(envfile_path, "r") as file:
            env_vars = [
                line.replace("export ", "").split("=")[0].strip()
                for line in file
                if "=" in line
            ]
    # else:
    #     raise MissingEnvTemplateFileError("No env template file present!")

    return env_vars


def process_env_file(env_dir: Path):
    all_envs = set()

    for repo in REPOS:
        envfile_path = MAIN_DIR / repo / "env.template"
        if not envfile_path.exists():
            envfile_path = MAIN_DIR / repo / ".env.template"
        all_envs.update(read_env_vars(envfile_path))

    envfile_path = env_dir / ".env"
    if envfile_path.exists():
        current_envs = set()

        current_envs.update(read_env_vars(envfile_path))

        ## validate current envs and all envs

        # Update envs
        update_envs = all_envs - current_envs
        # Delete envs
        delete_envs = current_envs - all_envs

        # add_comments
        if update_envs or delete_envs:
            create_or_add_comments(envfile_path, update_envs, delete_envs)

            print(
                "Found missing envs in .env file, please update and delete the comments"
            )
            return

        # log
        print("Env file processed : No Changes")

    else:

        # Update envs
        update_envs = all_envs
        # add comments
        create_or_add_comments(envfile_path, update_envs)

        # log
        print("Created .env file, please update and remove the comments")


def create_or_add_comments(
    envfile_path: Path, update_envs: set, delete_envs: Optional[set] = None
):

    processed_lines = []

    if envfile_path.exists():
        with open(envfile_path, "r") as file:
            lines = file.readlines()

        for line in lines:
            stripped_line = line.strip()
            if stripped_line and not stripped_line.startswith("#"):
                key = stripped_line.split("=")[0].strip()
                if delete_envs and key in delete_envs:
                    processed_lines.append(f"\n#delete variable\n{line}")
                else:
                    processed_lines.append(line)
            else:
                processed_lines.append(line)

    # Add new variables in update_envs at the end
    if update_envs:
        for update_var in update_envs:
            processed_lines.append(f"\n#update variable :\n{update_var}=\n")

    # Write back to the .env file
    with open(envfile_path, "w") as file:
        file.writelines(processed_lines)


def install_certs(certs_path: Path) -> bool:
    certs_path.mkdir(exist_ok=True, parents=True)

    if not (certs_path / "fullchain.pem").exists():
        # install certificates
        exec(
            'openssl req -x509 -newkey rsa:4096 -keyout privkey.pem -out fullchain.pem -sha256 -days 3650 -nodes -subj "/C=XX/ST=StateName/L=CityName/O=CompanyName/OU=CompanySectionName/CN=CommonNameOrHostname"',
            cwd=certs_path,
        )
        return True

    return False


def install_config(config_file: Path) -> bool:
    if not config_file.exists():
        config_template_path = MAIN_DIR / "ta2-minmod-kg" / "config.yml.template"

        processed_lines = []

        with open(config_template_path, "r") as file:
            lines = file.readlines()

        for line in lines:
            if line.startswith("#"):
                processed_lines.append(
                    "# update the below secret key with : openssl rand -hex 32"
                )
            elif line.startswith("secret_key"):
                processed_lines.append("\nsecret_key:")
            else:
                processed_lines.append(line)

        with open(config_file, "w") as file:
            file.writelines(processed_lines)

        return True

    return False


def export_env(file_path: Path):

    with open(file_path) as env_file:
        for line in env_file:
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip().strip('"')

    print(f"Environment variables from {file_path} have been exported.")


def validate_envfile(envfile_path: Path):

    with open(envfile_path, "r") as file:
        lines = file.readlines()

    for line_num, line in enumerate(lines, start=1):
        stripped_line = line.strip()
        if stripped_line.startswith("#"):
            raise EnvFileValidationError(
                f"Comment found on line {line_num}: {line.strip()}"
            )

    print("Validation passed: No comments found in the .env file.")


def build_repo(repo_dir: Path):
    network_ls = exec_output(
        f"docker network ls --filter name=minmod --format '{{{{.Name}}}}'", cwd=repo_dir
    )
    existing_networks = network_ls.strip().splitlines()
    if "minmod" not in existing_networks:
        exec("docker network create minmod", cwd=repo_dir)
    for repo in REPOS:
        repo_path = repo_dir / repo
        if (repo_path / "docker-compose.yml").is_file():
            print("Building repository", repo)
            exec("docker compose --env-file ../../.env build", cwd=repo_path)

        # if repo == "ta2-minmod-kg":
        #     # install dependencies
        #     repo_path = repo_dir / repo
        #     if not (repo_path / ".venv").exists():
        #         exec(f"{sys.executable} -m venv .venv", cwd=repo_path)
        #     exec("poetry lock", cwd=repo_path)
        #     exec("poetry install --only main", cwd=repo_path)


def build():
    is_updated = {}
    for repo in REPOS:
        is_updated[repo] = update_repo(repo)

    # setup the other directories.
    (MAIN_DIR / "kgdata").mkdir(exist_ok=True, parents=True)
    (MAIN_DIR / "kgdata" / "cdr").mkdir(exist_ok=True, parents=True)

    install_certs(ROOT_DIR / "certs")
    install_config(CFG_FILE)

    # setup, validate, and export env variables
    if not (ROOT_DIR / ".env").exists():
        shutil.copy(ROOT_DIR / ".env.template", ROOT_DIR / ".env")
    process_env_file(ROOT_DIR)
    validate_envfile(ROOT_DIR / ".env")
    validate_envfile(ROOT_DIR / "config.yml")
    export_env(ROOT_DIR / ".env")

    # build the docker images
    build_repo(MAIN_DIR)
    exec("docker compose --env-file .env build", cwd=ROOT_DIR)


if __name__ == "__main__":
    build()
