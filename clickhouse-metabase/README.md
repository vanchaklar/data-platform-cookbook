# ClickHouse + Metabase

A standalone local recipe for exploring ClickHouse through Metabase. It starts:

- ClickHouse with an empty `warehouse` database and persistent data volume.
- Metabase Open Source with its bundled ClickHouse driver.
- PostgreSQL for Metabase's own users, questions, dashboards and connection settings.
  This application database is separate from the ClickHouse data being analyzed.

Start the stack, then complete Metabase setup and the connection test in your browser.

## Versions and requirements

| Component | Pinned image |
| --- | --- |
| ClickHouse | `clickhouse/clickhouse-server:26.8.11.7` |
| Metabase | `metabase/metabase:v0.58.35` |
| Metabase application DB | `postgres:16.15-alpine3.24` |

Requires Docker with Compose v2 supporting `up --wait`, GNU Make, and Python 3.10+
for the local checks. Python uses only its standard library. Allow at least 6 GiB of
memory for Docker; the service limits total 4.5 GiB. First startup may take several
minutes while images download and Metabase initializes PostgreSQL.

The ClickHouse driver is bundled with Metabase starting in version 54; **do not download an
extra driver JAR** for this recipe. See the [official driver notice](https://github.com/ClickHouse/metabase-clickhouse-driver),
[Metabase release](https://github.com/metabase/metabase/releases/tag/v0.58.35),
[ClickHouse connection settings for v0.58](https://www.metabase.com/docs/v0.58/databases/connections/clickhouse),
and [Metabase's Docker/application-database guide](https://www.metabase.com/docs/latest/installation-and-operation/running-metabase-on-docker).

## Start

Run everything below from this directory:

```sh
cp .env.example .env  # first run only; keep an existing .env
make unit
make up
make smoke
```

Published endpoints are loopback-only:

- Metabase: <http://127.0.0.1:33000>
- ClickHouse HTTP: <http://127.0.0.1:38123>
- PostgreSQL has no published host port.

Change `METABASE_PORT` or `CLICKHOUSE_HTTP_PORT` in `.env` if a host port is occupied.
These host-side ports do not change the ports used between containers.

The passwords in `.env.example` are public, local-only examples. Use this stack
only with disposable development data on a trusted machine. HTTP is unencrypted,
and the ClickHouse development account is not a production least-privilege BI
account. Do not expose this recipe publicly or put real credentials in the repo.

## Connect Metabase to ClickHouse

1. Open Metabase and complete its first-run setup, choosing your own administrator
   credentials. The recipe does not create or store a preset admin login.
2. Select **ClickHouse** when adding your database, either during setup or through
   **Admin settings → Databases → Add a database**. Fill in the individual fields:

   | Field | Value |
   | --- | --- |
   | Display name | `Local ClickHouse` (or a name you choose) |
   | Host | `clickhouse` |
   | Port | `8123` |
   | Username | `cookbook`, or your `.env` `CLICKHOUSE_USER` |
   | Password | `local-clickhouse-only`, or your `.env` `CLICKHOUSE_PASSWORD` |
   | Databases | `warehouse` |
   | Scan all databases | Off |
   | SSL / secure connection | Off for this local stack |
   | SSH tunnel | Off |

   Leave the connection-string field empty. `clickhouse` is the Compose service
   hostname. **Do not use `localhost` or host port `38123` here:** from inside
   Metabase, `localhost` refers to the Metabase container. `metabase-db:5432` is
   used only for Metabase's application storage, not as your analytical source.

3. Save the connection. Open **New → SQL query**, choose **Local ClickHouse**, and
   run this non-mutating query:

   ```sql
   SELECT name AS database, version() AS clickhouse_version, 1 AS ok
   FROM system.databases WHERE name = 'warehouse';
   ```

   Expect `database = warehouse`, a ClickHouse version beginning `26.8.11.7`, and
   `ok = 1`. This is the actual Metabase-to-ClickHouse driver/query check. An empty
   table browser is expected until you add your own development tables.

## Checks and their limits

```sh
make unit      # offline tests; no Docker, network, accounts or third-party packages
make validate  # Docker Compose configuration validation only
make smoke     # read-only checks of the running development stack
make test      # unit tests + fresh disposable stack + smoke checks + cleanup
```

`make smoke` verifies PostgreSQL SQL, authenticated ClickHouse HTTP SQL against
`warehouse`, and Metabase's `/api/health`. It resolves actual loopback port mappings
and bypasses HTTP proxies and redirects. These checks **do not prove that a
ClickHouse data source has been registered in Metabase or that its driver can run
a query**. Complete the browser query above for that final check.

`make test` uses a unique Compose project, ephemeral loopback ports and independent
volumes. It creates no Metabase administrator or data-source connection. It removes
only its disposable project's containers and volumes on exit, and saves local
diagnostics under ignored `artifacts/`. `make smoke` does not delete or seed data.

Validation status when added: the offline tests, shell syntax and official Compose
JSON schema checks passed.
Docker was unavailable in the implementation environment, so Compose validation,
image pulls, startup, live smoke checks and the browser query remain unverified.
There is no CI configuration; all checks are invoked locally.

## Persistence, shutdown and troubleshooting

```sh
make logs
make down
```

`make down` preserves both named volumes. Starting again retains ClickHouse data
and Metabase setup. Back up both stores before upgrading pins. Never use
`docker compose down --volumes` on a stack whose data you want to keep.

- If startup fails, inspect `docker compose ps -a` and `make logs`; ensure Docker
  has enough memory. Rerunning `make up` keeps existing volumes.
- If the Metabase connection fails, check `clickhouse:8123`, SSL off, and the
  ClickHouse credentials. `make smoke` checks the services separately to narrow
  down the failure.
- PostgreSQL's initialization credentials apply only to an empty volume. Editing
  `METABASE_DB_PASSWORD` after setup does not rotate the existing PostgreSQL user's
  password and can prevent Metabase from starting. Keep the configured value or
  perform an intentional database credential rotation; do not delete data as a fix.
- Changing ClickHouse credentials also requires updating its saved connection in
  Metabase. Real deployments need dedicated read-only BI credentials, secret
  management, TLS, backups and appropriate access controls.

Logs can contain connection details. Review them before sharing diagnostics.
