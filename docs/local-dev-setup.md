# Running the Full Stack Locally

This sets up MinMod's whole write/sync pipeline on a laptop — Postgres, the API, the editor, nginx, Fuseki, and the async sync job — from the actual images and compose files each repo already has, no separate tooling. Useful for testing anything that touches the GeoChem `Sample` write path (or mineral sites) end to end, including the async triple-store/git sync, without touching production.

Tested against `ta2-minmod-kg`, `ta2-minmod-editor`, and `ta2-minmod-infra` on 2026-09-10. Assumes the four repos are checked out as siblings, e.g.:

```
<some-dir>/
├── ta2-minmod-kg
├── ta2-minmod-editor
├── ta2-minmod-infra
└── ta2-minmod-data          # only needed for the optional git-backup step
```

## What this does and doesn't give you

- **Real Postgres, real API, real editor UI, real nginx routing** — you can log in, browse mineral sites, and hit every `/api/v1/*` endpoint exactly as deployed.
- **Real async sync** (optional, §8–9) — Fuseki and a git-backed JSON snapshot, via the actual `api_sync` service, not a stand-in.
- **No mineral-site/entity data** unless you restore a Postgres dump (§3) — a fresh instance starts empty except for whatever `create_db_and_tables()` creates (empty tables).
- **No real users** — even a restored dump won't have any; you create one yourself (§5). See "why" below if you're restoring a dump that's suspiciously missing its `user` table.
- **Not connected to the real GeoChem HMI** — if you're testing the `/geochem` tab specifically, the iframe will hit the real Jataware-hosted app, which won't recognize a locally-issued session (see the note in `ta2-table-understanding` issue #17's comments). Everything else works.

## 1. One-time setup

```bash
docker network create minmod
```

Generate a local cert (nginx needs `fullchain.pem`/`privkey.pem`; a self-signed one is fine, your browser will just warn once):

```bash
mkdir -p /tmp/minmod-certs
openssl req -x509 -newkey rsa:4096 -keyout /tmp/minmod-certs/privkey.pem \
  -out /tmp/minmod-certs/fullchain.pem -sha256 -days 3650 -nodes \
  -subj "/CN=localhost"
```

Create a config file for the API (copy the template, generate your own secret rather than reusing the one checked into the repo):

```bash
cp ta2-minmod-kg/config.yml.template /tmp/config.yml
SECRET=$(openssl rand -hex 32)
# macOS: sed -i '' ; Linux: sed -i
sed -i '' "s/^secret_key:.*/secret_key: $SECRET/" /tmp/config.yml
```

Leave `triplestore` in `config.yml` pointing at `http://kg:3030/...` — nothing connects to it eagerly, so it's harmless even if you skip §8–9.

Every `docker compose` command below needs these exported in the shell you run it from:

```bash
export USER_ID=$(id -u) GROUP_ID=$(id -g)
export CERT_DIR=/tmp/minmod-certs
export CFG_FILE=/tmp/config.yml
```

## 2. Postgres

```bash
cd ta2-minmod-kg
docker compose build kg-postgres
docker compose up -d kg-postgres
```

⚠️ **This creates its own Docker network (`minmod_default`)**, not the shared `minmod` network the other services need — the compose file doesn't declare a `networks:` key for this service. Connect it manually, **with the alias**, or `api` won't be able to resolve the hostname `kg-postgres`:

```bash
docker network connect --alias kg-postgres minmod minmod-kg-postgres-1
```

(A plain `docker network connect minmod ...` without `--alias` looks like it works — the container joins the network — but only resolves by its container name, not the `kg-postgres` hostname the API's connection string expects. Found this the hard way; it fails as a DNS resolution error inside the API container, not an obviously-related error.)

## 3. Restore real data (optional)

If you have a Postgres dump (custom-format, from `pg_dump`) with real mineral-site/entity data, restore it now — before starting the API, so `create_db_and_tables()` doesn't race with the restore:

```bash
docker cp /path/to/your_dump.dump minmod-kg-postgres-1:/tmp/dump.dump
docker exec minmod-kg-postgres-1 pg_restore -U minmod -d minmod \
  --no-owner --no-privileges -j 4 /tmp/dump.dump
```

Skip this entirely for a fresh empty instance — the editor and API both work fine with zero rows, you just won't have anything to browse until you create data through the API yourself.

If your dump is missing `user`/`event_log`/`sample` — that's not a mistake in the dump, those tables aren't ETL-managed the same way the entity/mineral-site tables are. Either way, the API creates them fresh on first boot regardless (§4), and you create a user yourself (§5).

## 4. API

```bash
cd ta2-minmod-kg
docker compose build api
docker compose up -d api
```

Check it came up clean:

```bash
docker compose logs api | tail -20
curl -sk http://localhost:8000/api/v1/commodities | head -c 200
```

If you restored a dump, that last command should return real entities, not `[]`.

## 5. Create a test user

```bash
docker exec minmod-api-1 python -m minmodkg.api user \
  -u testuser -n "Test User" -e testuser@example.com --password 'Test1234!'
```

(`--password` skips the interactive prompt — fine for a local throwaway account; don't script it this way against production.)

Verify:

```bash
curl -sk -X POST http://localhost:8000/api/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"Test1234!"}'
```

## 6. Editor

```bash
cd ta2-minmod-editor
docker compose build editor
```

Nothing to run yet — `ta2-minmod-infra`'s compose file (next step) starts it with the right port/command. `MINMOD_API` is a runtime env var read by the editor's Flask backend, not baked in at build time, so it doesn't matter what the image's own compose file defaults it to.

## 7. nginx (ties it all together)

```bash
cd ta2-minmod-infra
docker compose build nginx
docker compose up -d editor nginx
```

This starts `editor` and `nginx` using *this* repo's compose definitions (correct ports/`MINMOD_API` value), even though the image was built from `ta2-minmod-editor`'s own compose file in the previous step.

Now check everything through the actual proxy:

```bash
curl -sk -o /dev/null -w "%{http_code}\n" https://localhost/          # editor, expect 200
curl -sk -o /dev/null -w "%{http_code}\n" https://localhost/api/v1/whoami   # expect 401/403, not logged in yet
```

Open `https://localhost` in a browser (click through the self-signed cert warning) and log in as `testuser` / `Test1234!`.

## 8. Async sync — Fuseki + triple store (optional)

Skip this section entirely if you only need to verify Postgres-backed reads/writes (the editor UI, `PATCH`/`PUT` responses, etc.) — that's everything in §1–7. This section is for verifying the *second half* of the write path: does a save actually propagate into the triple store and the git-backed JSON backup.

**Fuseki isn't a `docker compose` service** — production starts it with a plain `docker run`, and we do the same locally:

```bash
mkdir -p /tmp/minmod-kgdata
docker run --name minmod-kg-1 -d -p 127.0.0.1:3030:3030 \
  -v /tmp/minmod-kgdata:/home/criticalmaas/databases \
  --network=minmod --network-alias=kg \
  minmod-fuseki fuseki/fuseki-server --config=fuseki/config.ttl
```

(Build the image first if you haven't: `cd ta2-minmod-kg && docker compose build kg`.)

Check it's up and the `/minmod` dataset responds:

```bash
curl -s http://localhost:3030/\$/ping
curl -s "http://localhost:3030/minmod/sparql?query=SELECT+(COUNT(*)+as+%3Fc)+WHERE+%7B%3Fs+%3Fp+%3Fo%7D"
```

Now run the actual sync service (same code, same command, as the real `api_sync` container) against your running API container:

```bash
docker exec -d minmod-api-1 python -m minmodkg.services.sync /tmp/nonexistent-data-dir --backup-interval 0 --verbose
```

`--backup-interval 0` disables the git-backup half entirely (see §9 for why that matters) — this only drains `event_log` into Fuseki. Make an edit through the API or editor UI, then re-run the SPARQL count query above; it should go up. `SELECT id, type, kg_synced, backup_synced FROM event_log` in Postgres should show `kg_synced = t` for your event (rows are deleted once *both* `kg_synced` and `backup_synced` are true — with backup disabled, expect them to stay in the table with `backup_synced = f`).

Stop it when you're done — it loops forever otherwise:

```bash
docker exec minmod-api-1 pkill -f minmodkg.services.sync
```

## 9. Async sync — git backup (optional, read the warning first)

⚠️ **`BackupListener` ends every sync cycle with a real `git push`** (`GitRepository(repo_dir).commit_all(...).push()`, no dry-run mode). If you point this at an actual clone of `ta2-minmod-data` with its real `origin` still configured, this **will push commits to the real GitHub repo.** Do not do that. Set up a throwaway local repo first:

```bash
docker exec minmod-api-1 sh -c '
  git config --global user.email "you@example.com"
  git config --global user.name "Local Dev"
  git init --bare /tmp/fake-origin.git
  git clone /tmp/fake-origin.git /tmp/fake-data-repo
  cd /tmp/fake-data-repo && git commit --allow-empty -m "initial" && git push -u origin main
'
```

Confirm `origin` is the local path, not GitHub, before going further: `docker exec minmod-api-1 git -C /tmp/fake-data-repo remote -v`.

Now run the sync service pointed at that local repo, with a short backup interval so you don't wait an hour:

```bash
docker exec -d minmod-api-1 python -m minmodkg.services.sync /tmp/fake-data-repo --backup-interval 1 --verbose
```

After it runs (check `git -C /tmp/fake-data-repo log --oneline` for a new "Backup data as of ..." commit), `event_log` rows for fully-synced events disappear entirely — that table is a transient dispatch queue, not permanent history. Stop the process the same way as §8.

## Tearing down

```bash
cd ta2-minmod-infra && docker compose down
cd ../ta2-minmod-kg && docker compose down
docker rm -f minmod-kg-1   # Fuseki, if you started it — not managed by compose
```

## Alternatives

- **Skip the local build entirely** and point `ta2-minmod-editor`'s dev server (`npm start` in `www/`) at a real or already-running MinMod API instead of building this whole stack — much faster for frontend-only changes, but you lose the ability to test anything nginx-routed (like an embedded iframe tab) and anything that needs a real backend session cookie set by a real login.
- **`mms/build.py`/`mms/update.py`** (`ta2-minmod-infra`) automate a version of this bring-up for the production host, including the full ETL to populate Fuseki from `ta2-minmod-data` from scratch — a much heavier process, meant for standing up a new deployment, not quick local iteration. This document is the fast path for the latter.
