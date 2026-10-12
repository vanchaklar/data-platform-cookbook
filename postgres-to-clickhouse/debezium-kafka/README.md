# Debezium + Kafka infrastructure scaffold

**Status: infrastructure scaffold only. There is no registered Debezium source
connector, ClickHouse sink, or end-to-end CDC pipeline in this directory.**

This independent recipe starts PostgreSQL with logical WAL, a single-node Kafka
KRaft broker, a Debezium Kafka Connect worker, and ClickHouse. It provides pinned
dependencies and disposable infrastructure checks as a starting point for a
PostgreSQL-to-ClickHouse CDC pipeline.

## Requirements and pinned dependencies

- Docker Engine with Docker Compose v2 supporting `up --wait` and `config --format json`
- Bash, GNU Make, and Python 3.9+ on the host (standard library only)
- At least 6 GiB RAM available to Docker is recommended
- PostgreSQL: `postgres:16.15-alpine3.24`
- Kafka: `apache/kafka:4.1.2`
- Debezium Connect: `quay.io/debezium/connect:3.3.2.Final`
- ClickHouse: `clickhouse/clickhouse-server:26.8.11.7`

Image tags are deliberately fixed in `compose.yaml`. No custom images or Python
packages are needed. These are a development baseline, not a production security
or availability configuration.

## Start and inspect

Run commands from this directory:

```sh
cp .env.example .env  # optional: defaults already work for local development
make up
make smoke
docker compose ps
make down
```

`make up` validates Compose and waits for all four service health checks.
`make smoke` checks the currently selected development project. `make down` stops
it without removing persistent data. No command silently resets development
volumes. If you explicitly want to discard all data in this recipe's development
stack, review the project name first and run `docker compose down --volumes`.

Default project: `cookbook-debezium-kafka`. It has its own network and volumes,
independent of the adjacent MaterializedPostgreSQL recipe. Set
`COMPOSE_PROJECT_NAME` consistently when you need another development instance.

Only IPv4 loopback ports are published:

- PostgreSQL: `127.0.0.1:25432`, database `source`
- ClickHouse HTTP: `http://127.0.0.1:28123`, database `warehouse`
- Kafka Connect REST: `http://127.0.0.1:28083`

Usernames/passwords and development host ports are configurable in `.env`; its
example values are public local-only credentials. Changing a database password
in `.env` does not update an already initialized PostgreSQL volume.

Kafka is reachable as `kafka:9092` only within its Compose network. Use
`docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list`
to inspect it. Kafka and Connect have no authentication or TLS in this local
scaffold. Do not expose these services or use private/production data here.

## Local tests

```sh
make unit      # offline Python helper tests; no Docker needed
make validate  # Compose model validation; requires Docker Compose CLI
make test      # complete disposable infrastructure smoke test
```

`make test` runs the offline tests, validates Compose, creates a unique isolated
project with fresh volumes, starts healthy dependencies, and verifies:

1. PostgreSQL executes SQL and reports `wal_level=logical`.
2. ClickHouse accepts an authenticated HTTP `SELECT 1`.
3. Connect's plugin list includes the Debezium PostgreSQL connector class.
4. Kafka creates a uniquely named topic, produces one synthetic message, consumes
   the exact message, then deletes only that topic.

Tests publish ephemeral ports on `127.0.0.1`, so they can run beside the normal
development stack. They do not reuse `.env` credentials or development volumes.
On success or failure, a shell trap captures logs and removes only the unique
test project's containers, network, and volumes. A failed cleanup fails the test.
Diagnostics are under ignored `artifacts/`: `project.txt`, `services.txt`,
`compose.log`, and `smoke.log` (when the smoke stage started). A forced kill or
Docker outage can prevent cleanup; use the exact name in `artifacts/project.txt`
when inspecting or cleaning up that test project.

Docker must be available to run `make test`. Passing `make unit` alone is not proof that these images start,
that the live smoke checks pass, or that CDC works.

## What remains for a complete CDC solution

A complete implementation must choose and test source tables, replication
permissions/publications/slots, a registered Debezium connector, topic and event
format conventions, and a ClickHouse ingestion mechanism. It must define initial
snapshot behavior, primary keys, update/delete semantics, restart recovery,
schema changes, observability, authentication, and production resource limits.

PostgreSQL has a 1 GiB retained-WAL cap for slots in this local scaffold. A stalled
future consumer can outgrow this cap and require recovery; logical WAL alone is
not a replication guarantee. Single-node Kafka and replication factor one offer
no redundancy. Plugin discovery verifies availability, not a configured or
running source connector. There is no automated PostgreSQL-to-ClickHouse data
movement or verification in this recipe.

References: [Debezium PostgreSQL connector](https://debezium.io/documentation/reference/3.3/connectors/postgresql.html),
[Debezium Connect entrypoint](https://github.com/debezium/container-images/blob/main/connect-base/3.3/docker-entrypoint.sh),
[Docker Compose CLI](https://docs.docker.com/reference/cli/docker/compose/).
