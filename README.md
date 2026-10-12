# Data Platform Cookbook

Small, independently runnable data-platform solutions, with Docker Compose and local tests.
Each recipe demonstrates a reusable integration pattern with a small, focused example.

## Recipes

- [PostgreSQL to ClickHouse](postgres-to-clickhouse/)
  - [MaterializedPostgreSQL](postgres-to-clickhouse/materialized-postgresql/): executable
    native replication example, append-only change history and deletion-aware current state.
  - [Debezium/Kafka](postgres-to-clickhouse/debezium-kafka/): infrastructure scaffold and
    service smoke checks. Connector/sink configuration is not implemented yet.

Each solution has its own directory, Compose project, README, tests and pinned
versions. There is no global stack that starts unrelated solutions.

Adapt a recipe to your own schema and workload, and record the cookbook commit used.
Do not treat these local development examples as production deployments.
