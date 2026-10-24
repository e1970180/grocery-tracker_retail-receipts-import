# Deployment

The service runs on the home server as one compose service with one named volume. PostgreSQL is
the existing LAN instance (18.6 or later) and is not part of compose. Each environment has its
own database and three login roles:

| Role | Used by | May do |
| --- | --- | --- |
| schema owner (`rri_dev_owner`) | `migrate` only | connect to its database; owns `retail_receipts_import` and `resolver_v1` |
| writer (`rri_dev_writer`) | the service | connect to its database; read `public.chains_v1`; read and insert `receipts`; insert lines, settlements and feed rows |
| Resolver reader (`resolver_dev_reader`) | the Resolver | connect to its database; read the views in `resolver_v1` |

None of them may connect to any other database, update or delete a receipt, or touch the
migrations ledger. `dev` needs a database name ending in `-dev`; `prod` one that does not.

Only the home server holds the writer's password. In dev, the workstation works as a fourth role,
`rri_dev_developer`: a member of the schema owner, with CONNECT, CREATE and TEMPORARY on the dev
database and SELECT on `public.chains_v1`. Production has no such role.

The SQL steps need `psql`. Where it is not installed, run it from the PostgreSQL image with the
repository mounted, for example on the home server:

```bash
docker run --rm -it -v "$PWD":/repo -w /repo postgres:18.6 psql -h <host> -p <port> -U postgres -d postgres
```

## 1. Close the other databases (admin, once per cluster)

PostgreSQL grants CONNECT and TEMPORARY on every new database to PUBLIC. Revoke that on every
database other than the environment's own, after granting the same rights explicitly to the
other login roles that use them:

```sql
GRANT CONNECT, TEMPORARY ON DATABASE "<other_db>" TO <other_login_roles>;
REVOKE ALL ON DATABASE "<other_db>" FROM PUBLIC;
```

A role created on the cluster later then needs an explicit CONNECT to reach those databases.

## 2. Provision the environment (admin, once per environment)

From the repository root, here or on the home server after step 3 (the script includes
`docs/contracts/chains_v1.sql`):

```bash
psql -h <host> -p <port> -U postgres -d postgres -v ON_ERROR_STOP=1 -v db=grocery-tracker-dev -v owner=rri_dev_owner -v writer=rri_dev_writer -v reader=resolver_dev_reader -f docs/deploy/provision.sql
```

It creates the roles (psql asks for their passwords), the database, both schemas with their
default privileges, and the chain reference with the writer's SELECT.

## 3. Check out and build (home server)

A sparse checkout holds only what the image needs:

```bash
git clone --no-checkout --filter=blob:none https://github.com/e1970180/grocery-tracker_retail-receipts-import ~/grocery-tracker/retail-receipts-import
```

```bash
cd ~/grocery-tracker/retail-receipts-import && git sparse-checkout set --no-cone /Dockerfile /compose.yaml /.dockerignore /.env.example /pyproject.toml /uv.lock /README.md /src/ /migrations/ /texts/ /docs/deploy/ /docs/contracts/ && git checkout main
```

Copy `.env.example` to `.env` and fill it in with the writer's credentials; keep the schema
owner's out of it. Then build:

```bash
docker compose build
```

## 4. Migrate (every deploy)

Export the schema owner's credentials in the shell for this run only, typing the password at a
silent prompt so it stays out of the shell history, and `unset` both afterwards:

```bash
export RRI_MIGRATE_DB_USER=rri_dev_owner; read -rs RRI_MIGRATE_DB_PASSWORD; export RRI_MIGRATE_DB_PASSWORD
```

```bash
docker compose run --rm -e RRI_MIGRATE_DB_USER -e RRI_MIGRATE_DB_PASSWORD receipts migrate
```

Then always trim the writer (idempotent, as the schema owner). The default privileges give it
SELECT, INSERT on every table a migration creates, the migrations ledger included, until this
runs:

```bash
psql -h <host> -p <port> -U rri_dev_owner -d grocery-tracker-dev -v ON_ERROR_STOP=1 -v writer=rri_dev_writer -f docs/deploy/after-migrate.sql
```

## 5. Start

One Telegram bot serves dev and production, and Telegram gives updates to one poller at a time.
Before starting, stop every other instance of the service, wherever it runs.

```bash
docker compose up -d
```

```bash
docker compose logs -f receipts
```

## Update

```bash
git pull --ff-only && docker compose build
```

When the update brings a new migration, run step 4 now, before the new code starts. Then:

```bash
docker compose up -d
```
