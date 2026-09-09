# Running the Core Stack Locally (No Docker)

This sets up Postgres, the API, and the editor natively — no containers — so you can test anything that reads/writes mineral sites or GeoChem samples through the real API against real data. It deliberately does not cover nginx or Fuseki: without those, you get the editor's dev server directly (no `/geochem`, `/dashboard`, or SPARQL routing) and no triple-store/git sync, only the Postgres-backed read/write path. That's enough for iterating on API endpoints (like GeoChem `Sample` `PATCH`) or the editor UI.

Tested against `ta2-minmod-kg` and `ta2-minmod-editor` on 2026-09-10, on macOS with Homebrew. Assumes the repos are checked out as siblings:

```
<some-dir>/
├── ta2-minmod-kg
└── ta2-minmod-editor
```

## 1. Postgres

Install and start it (Homebrew on macOS; use your distro's package manager on Linux — e.g. `apt install postgresql`):

```bash
brew install postgresql@17
brew services start postgresql@17
```

`postgresql@17`'s binaries (`psql`, `pg_restore`, ...) may be shadowed by another `psql` already on your `PATH` (e.g. from a `libpq`-only install) — if `which psql` doesn't point under `postgresql@17`, prefix commands below with `/opt/homebrew/opt/postgresql@17/bin/`, or put it first on `PATH` for this session:

```bash
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
```

Create the role and database the API expects:

```bash
psql postgres -c "CREATE ROLE minmod WITH LOGIN PASSWORD 'criticalmaas2025';"
psql postgres -c "CREATE DATABASE minmod OWNER minmod;"
```

### Restore real data (optional)

If you have a Postgres dump (custom-format, from `pg_dump`) with real mineral-site/entity data:

```bash
pg_restore -U minmod -d minmod -h localhost --no-owner --no-privileges -j 4 /path/to/your_dump.dump
```

Skip this for a fresh empty instance — the API creates all its tables on first boot regardless (§2), you just won't have anything to browse until you create data yourself. If your dump is missing `user`/`event_log`/`sample`, that's expected — those tables aren't ETL-managed the same way the entity/mineral-site tables are. Either way you create a user in §3.

## 2. API

Needs Python 3.11+ and Poetry:

```bash
brew install poetry   # or: pipx install poetry

cd ta2-minmod-kg
python3.11 -m venv .venv
source .venv/bin/activate
poetry install --only main
```

If you hit `pyproject.toml changed significantly since poetry.lock was last generated`, run `poetry lock` first, then retry `poetry install --only main`.

Create a config file (copy the template, generate your own secret, point `kgrel` at your local Postgres instead of the Docker hostname the template ships with):

```bash
cp config.yml.template /tmp/native-config.yml
SECRET=$(openssl rand -hex 32)
# macOS: sed -i '' ; Linux: sed -i
sed -i '' "s/^secret_key:.*/secret_key: $SECRET/" /tmp/native-config.yml
sed -i '' "s|kgrel:.*|kgrel: postgresql+psycopg://minmod:criticalmaas2025@localhost:5432/minmod|" /tmp/native-config.yml
```

Leave `triplestore` pointing at `http://kg:3030/...` — nothing connects to it eagerly, so it's harmless with no Fuseki running.

Run it:

```bash
export CFG_FILE=/tmp/native-config.yml
fastapi run minmodkg/api/main.py --port 8000
```

(Leave this running in its own terminal, or background it with `nohup ... &` if you're scripting this.)

Check it came up clean, in a second terminal:

```bash
curl -s http://localhost:8000/api/v1/commodities | head -c 200
```

If you restored a dump, that should return real entities, not `[]`.

## 3. Create a test user

Same shell, same `CFG_FILE`:

```bash
python -m minmodkg.api user \
  -u testuser -n "Test User" -e testuser@example.com --password 'Test1234!'
```

(`--password` skips the interactive prompt — fine for a local throwaway account; don't script it this way against production.)

Verify:

```bash
curl -s -X POST http://localhost:8000/api/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"Test1234!"}'
```

## 4. Editor

```bash
cd ta2-minmod-editor/www
npm install
npm start
```

This is Create React App's dev server on `:3000`, proxying `/api/*` straight to `http://localhost:8000` (see `"proxy"` in `package.json` — if your API is on a different port, that's the value to change, not an env var). Open `http://localhost:3000`, log in as `testuser`/`Test1234!`.

You'll see the real editor UI with real data (if you restored a dump) — mineral site search, filters, edit flows. What you *won't* see: the `/geochem` tab (it's `/geochem/`-routed via nginx in the real deployment, which isn't running here) or anything under `/dashboard`.

## Verifying a GeoChem sample edit end to end

With the API and a logged-in session from above, exercise the real write path directly:

```bash
# grab a real mineral_site_id to attach a sample to
SITE_ID=$(psql -U minmod -d minmod -h localhost -t -c "SELECT site_id FROM mineral_site LIMIT 1;" | xargs)

# log in and keep the session cookie
curl -s -c /tmp/cookies.txt -X POST http://localhost:8000/api/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"Test1234!"}' >/dev/null

# create a sample
curl -s -b /tmp/cookies.txt -X POST http://localhost:8000/api/v1/samples \
  -H "Content-Type: application/json" \
  -d "{\"mineral_site_id\": \"$SITE_ID\", \"sample_id\": \"SM-001\", \"description\": \"test\"}"

# edit it — only send what changed
curl -s -b /tmp/cookies.txt -X PATCH \
  "http://localhost:8000/api/v1/samples/sample__${SITE_ID}__sm-001" \
  -H "Content-Type: application/json" \
  -d '{"description": "edited"}'
```

The `PATCH` response's `edit_history` should show two entries, and `changed_properties` on the second should be exactly `["https://geochemistry.isi.edu/ontology/description"]` — confirming the sparse-patch merge (documented in `ta2-table-understanding` issue #18) is doing the right thing against real Postgres.

## Stopping

`Ctrl-C` the API and `npm start` processes. Postgres keeps running as a background service — `brew services stop postgresql@17` when you're done with it, or leave it running for next time.

## What this intentionally leaves out

- **nginx** — no `/geochem`, `/dashboard`, or path-based routing; you're talking to the editor's dev server and the API directly.
- **Fuseki / triple-store sync** — writes land in Postgres only; nothing propagates to RDF or to a JSON/git backup. If you need to verify that half of the pipeline, it needs a JVM (Fuseki) and either Docker or a manual Jena install — ask if you need that covered too.
- **The real GeoChem HMI** — even with nginx added back, the externally-hosted GeoChem HMI validates sessions against the real `minmod.isi.edu`, not a local instance (see `ta2-table-understanding` issue #17's comments) — there's no local way to see its actual UI functioning end to end.
