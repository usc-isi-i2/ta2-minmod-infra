# Overview

Code to help deploy TA2 KG and HMI

## Repository Structure

- [containers](/containers): scripts to build nginx docker image
- [main](/main): contains the configuration and code for individual services
- [build.py](/build.py): script to update the repo and build the docker images
- [.env](/.env): environment variables needed for the services
- [config.yml](/config.yml): configuration file for the services

## Installation

### General Installation

To setup the infrastructure, run the following commands (reqired Python >=3.11, Git & Git LFS):

```bash
git clone --depth 1 https://github.com/DARPA-CRITICALMAAS/ta2-minmod-infra.git
cd ta2-minmod-infra
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m mms.build
```

Everytime the build script is run, it will check if the environment variables (specified in [./.env](/.env) file) and the configuration file (specified in [./config.yml](./config.yml)) have correct values. If not, the script will inform the users to update the values in the files. For the first time setp, you need to update the secret key in the [./config.yml](./config.yml) file as instructed in the file. The [./.env](/.env) comes with the default values copied from [./.env.template](./.env.template), but you can update them as needed.

Note that the build script also creates a [./certs](./certs) directory for storing the SSL certificates and generates a self-signed certificate for the services. You can replace the self-signed certificate with your own certificate.

In order to back up data to the designated repository ([./main/ta2-minmod-data](./main/ta2-minmod-data) or [./main/ta2-minmod-data-sample](./main/ta2-minmod-data-sample)), you have to setup an Git account with push permission.

### EC2 Quick Start

For EC2 start fresh from the Amazon Linux image, you can run the following commands to setup Python3.11 and docker:

```bash
sudo dnf install -y htop git git-lfs python3.11 python3.11-pip

# setup docker
sudo dnf install -y docker
sudo usermod -a -G docker ec2-user
sudo service docker start
newgrp docker

# install docker compose
DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
mkdir -p $DOCKER_CONFIG/cli-plugins
curl -SL https://github.com/docker/compose/releases/download/v2.32.0/docker-compose-linux-x86_64 -o $DOCKER_CONFIG/cli-plugins/docker-compose
chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose

alias python=python3.11
echo 'alias python=python3.11' >> ~/.bashrc
```

Note: you need to open ports 80 and 443 to allow access to MinMod.

## Configuration

To change CDR endpoint, update the `CDR_API` environment variable in the [docker-compose.yml](./docker-compose.yml) file.

## Deployment

First, we need to run the building KG command

```bash
python -m mms.update [--test]
```

If the `--test` flag is provided, the script will build the KG on a small dataset for testing. Otherwise, it will build the KG with the full dataset.

After that, we can start the services by running the following command:

```bash
docker compose up -d nginx api editor api_sync api_cdr_sync; sleep 10; docker compose up -d dashboard
```

If you are testing the system, use `api_sync_test` instead:

```bash
docker compose up -d nginx api editor api_sync_test; sleep 10; docker compose up -d dashboard
```

Note that `api_sync` will back up the data to the github repository. You can create an access token and change the remote of the repository to include the access token with the following format: `https://<access_token>@<repository_url>`.

To clean up the databases, run the following command:

```bash
docker container rm -f $(docker container ls -aq --filter ancestor=minmod-fuseki)
docker container rm -f $(docker container ls -aq --filter ancestor=minmod-postgres)
rm -r main/kgdata/databases

```

To clean up the databases and all cache, run the following command:

```bash
docker container rm -f $(docker container ls -aq --filter ancestor=minmod-fuseki)
docker container rm -f $(docker container ls -aq --filter ancestor=minmod-postgres)
rm -r main/kgdata
```

After the services are started, you can access the services with your host IP address.

## Admin

We provide [APIs](https://minmod.isi.edu/api/v1/docs#/admin) to list the users and create users (need admin access). We also provide commands to create/delete users from files (no need permission -- see [ta2-minmod-kg/minmodkg/api/**main**.py](https://github.com/DARPA-CRITICALMAAS/ta2-minmod-kg/blob/main/minmodkg/api/__main__.py)). One way to execute these commands is to attach to the `api` container (e.g., `docker compose exec -it api bash`) and run them there.

For the full new-user onboarding process (starting from the account request form), see [docs/onboarding-new-user.md](./docs/onboarding-new-user.md).

## Recovering from a Server Reboot

`docker compose up` alone is not enough after a reboot — the Postgres and Fuseki data stores are started separately and won't come back automatically. See [docs/system-reboot-recovery.md](./docs/system-reboot-recovery.md) for the full ordered list of commands.
