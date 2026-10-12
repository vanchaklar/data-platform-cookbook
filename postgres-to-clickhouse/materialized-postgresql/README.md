# Native PostgreSQL to ClickHouse

An executable, domain-neutral recipe for PostgreSQL 16.15 and ClickHouse 26.8.11.7:

1. PostgreSQL source table → MaterializedPostgreSQL database engine.
2. Normal materialized view → append-only MergeTree change history.
3. Normal materialized view → ReplacingMergeTree(version, is_deleted) current state.

The example source uses `id`, `metric`, `payload`, and `updated_at` to demonstrate
snapshot loading and ongoing inserts, updates, and deletes.

## Run and verify

From this directory, with Docker Compose v2 and Make installed:

```sh
make test             # start services, run checks, clean only test-created databases
make demo             # run the example and retain its uniquely named databases
make down             # stop services; preserve persistent volumes
```

The retained demo prints its PostgreSQL database, ClickHouse mirror database and target
database names. Inspect the target with `SELECT * FROM <target>.current FINAL`, or
`SELECT * FROM <target>.history ORDER BY version, id` to see change records.
To remove a retained demo, use the exact names printed by that run and execute:

```sql
-- In ClickHouse, in this order:
DROP DATABASE <target_database> SYNC;
DROP DATABASE <mirror_database> SYNC;
-- Then in PostgreSQL, connected to the postgres maintenance database:
DROP DATABASE <postgres_database>;
```

Each retained mirror occupies a replication slot; this local stack allows four slots.
`make down` preserves both databases and volumes, so clean retained demos before
creating more. Never substitute the names of unrelated databases.

PostgreSQL is exposed at localhost:15432 and ClickHouse HTTP at localhost:18123.
Copy `.env.example` to `.env` to override local credentials, ports and `ID_RANGE_SIZE`.
All published ports are loopback-only. Container limits total under 3 GB; these are
local developer settings, not production security or sizing guidance.

## Current-state semantics

`version = _version` and `is_deleted = toUInt8(_sign = -1)` preserve replication metadata.
The destination uses `PARTITION BY intDiv(id, ID_RANGE_SIZE)` and `ORDER BY id`.
`ID_RANGE_SIZE=1000000` is a configurable example, not a maximum row/byte count.
Choose it before creating a destination and do not change it in place. All versions
and a key-only deletion marker must remain in the same partition.

Read current state with FINAL. ReplacingMergeTree merges are asynchronous; normal
queries can otherwise see multiple versions. Retain tombstones; do not run cleanup
that could allow replayed older rows to reappear. History keeps the original change
records independently of current-state replacement. Delivery/retry behavior can leave
duplicates in history; it is not advertised as an exactly-once event log.

Updates do not reliably contain full old rows. Deletes can contain only the key.
A further summing materialized view would not retract prior contributions when rows
are replaced. Derive aggregates from reconciled current state or implement an explicit
correction strategy in the application.

## Snapshot and schema boundary

Bootstrap runs while the example source is quiescent: load the initial snapshot,
create the two views, then backfill history (which feeds current state). Do not apply
this sequence to a concurrently changing production source without a tested snapshot/
stream handoff. Existing rows are not automatically replayed into a newly created MV.

The publication explicitly lists `id,metric,payload,updated_at`. Adding an unrelated
PostgreSQL column is tested and does not interrupt the stream, but that new column
is deliberately not replicated. Changing an included column, replication identity or
publication requires separate handling. REPLICA IDENTITY FULL is unsupported by this
engine version; use a primary key/default identity. The engine remains experimental.

Tests cover snapshot backfill, live insert/update/delete, ID-range boundaries,
older-version replay after a tombstone, history retention, primary-key updates and an
excluded-column addition. They do not establish production recovery guarantees,
failover, concurrent bootstrap correctness or included-column evolution.

Sources: [engine](https://clickhouse.com/docs/reference/engines/database-engines/materialized-postgresql),
[ReplacingMergeTree](https://clickhouse.com/docs/reference/engines/table-engines/mergetree-family/replacingmergetree),
[publication column lists](https://www.postgresql.org/docs/16/logical-replication-col-lists.html).
