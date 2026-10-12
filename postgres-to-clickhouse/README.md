# PostgreSQL to ClickHouse

Choose a solution; their runtimes are independent.

## materialized-postgresql/

PostgreSQL logical replication is consumed directly by ClickHouse's experimental
MaterializedPostgreSQL **database** engine. Normal materialized views retain a
change log and feed ReplacingMergeTree(version, is_deleted). ID-range partitioning
keeps updates and key-only deletion markers together. The example verifies this
behavior on pinned versions. Read its limitations before adopting it.

## debezium-kafka/

A separate PostgreSQL, Kafka, Debezium Connect and ClickHouse infrastructure scaffold.
Health checks verify the services and a Kafka roundtrip, but no CDC connector or
ClickHouse sink is registered. This directory deliberately does not claim a working
end-to-end CDC pipeline.

The native recipe trades fewer components for experimental-engine and schema
limitations. The Kafka route leaves room for an explicit event contract, replay and
broader schema handling, at the cost of more components.
