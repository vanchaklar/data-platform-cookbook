"""Disposable, quiescent-bootstrap PostgreSQL CDC example."""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import psycopg
from psycopg import sql


def range_size(value):
    result = int(value)
    if result < 4 or result > 2**62:
        raise ValueError('ID_RANGE_SIZE must be between 4 and 2**62')
    return result


def literal(value):
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def wait_until(predicate, label, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise TimeoutError(label)


class Recipe:
    def __init__(self):
        suffix = uuid.uuid4().hex[:12]
        self.source = 'cookbook_' + suffix
        self.mirror = 'mirror_' + suffix
        self.target = 'cdc_' + suffix
        self.size = range_size(os.getenv('ID_RANGE_SIZE', '1000000'))
        self.pg_options = dict(host=os.getenv('PGHOST', '127.0.0.1'),
                               port=os.getenv('PGPORT', '15432'),
                               user=os.getenv('PGUSER', 'lab'),
                               password=os.getenv('PGPASSWORD', 'local-postgres-only'))
        self.pg = None
        self.created_source = False

    def ch(self, query):
        params = urllib.parse.urlencode({'allow_experimental_database_materialized_postgresql': 1, 'output_format_json_quote_64bit_integers': 0})
        url = os.getenv('CLICKHOUSE_URL', 'http://127.0.0.1:18123').rstrip('/') + '/?' + params
        token = base64.b64encode((os.getenv('CLICKHOUSE_USER', 'lab') + ':' +
                                  os.getenv('CLICKHOUSE_PASSWORD', 'local-clickhouse-only')).encode()).decode()
        request = urllib.request.Request(url, data=query.encode(), headers={'Authorization': 'Basic ' + token})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode().strip()
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from error

    def rows(self, query):
        result = self.ch(query + ' FORMAT JSONEachRow')
        return [json.loads(row) for row in result.splitlines()]

    def current(self):
        return self.rows(f'SELECT id,metric,payload FROM {self.target}.current FINAL ORDER BY id')

    def setup(self):
        with psycopg.connect(**self.pg_options, dbname=os.getenv('PGDATABASE', 'postgres'), autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.source)))
            self.created_source = True
        self.pg = psycopg.connect(**self.pg_options, dbname=self.source, autocommit=True)
        self.pg.execute('CREATE TABLE records(id bigint PRIMARY KEY, metric bigint NOT NULL, payload text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())')
        self.pg.execute("INSERT INTO records(id,metric,payload) VALUES(1,10,'snapshot')")
        args = [str(self.pg_options['host']) + ':' + str(self.pg_options['port']), self.source,
                self.pg_options['user'], self.pg_options['password']]
        self.ch(f'CREATE DATABASE {self.mirror} ENGINE=MaterializedPostgreSQL(' + ','.join(map(literal, args)) + ") SETTINGS materialized_postgresql_tables_list='records(id,metric,payload,updated_at)'")
        wait_until(lambda: self.ch(f"SELECT count() FROM system.tables WHERE database='{self.mirror}' AND name='records'") == '1', 'mirror table creation')
        wait_until(lambda: self.ch(f'SELECT count() FROM {self.mirror}.records') == '1', 'snapshot')
        self.ch(f'CREATE DATABASE {self.target}')
        columns = "id Int64, metric Int64, payload String, updated_at DateTime64(6,'UTC'), version UInt64, is_deleted UInt8"
        self.ch(f'CREATE TABLE {self.target}.history({columns}) ENGINE=MergeTree ORDER BY (version,id)')
        self.ch(f'CREATE TABLE {self.target}.current({columns}) ENGINE=ReplacingMergeTree(version,is_deleted) PARTITION BY intDiv(id,{self.size}) ORDER BY id')
        self.ch(f'CREATE MATERIALIZED VIEW {self.target}.apply_current TO {self.target}.current AS SELECT * FROM {self.target}.history')
        selection = f'SELECT id,metric,payload,updated_at,_version AS version,toUInt8(_sign=-1) AS is_deleted FROM {self.mirror}.records'
        self.ch(f'CREATE MATERIALIZED VIEW {self.target}.capture TO {self.target}.history AS ' + selection)
        # Source writes remain paused until this snapshot backfill has finished.
        self.ch(f'INSERT INTO {self.target}.history ' + selection)

    def cleanup(self):
        # Attempt every cleanup step, even after one fails. Never mask the original error.
        original = sys.exception()
        errors = []
        for database in (self.target, self.mirror):
            try:
                self.ch(f'DROP DATABASE IF EXISTS {database} SYNC')
            except Exception as error:
                errors.append(error)
        if self.pg is not None:
            try:
                self.pg.close()
            except Exception as error:
                errors.append(error)
        if self.created_source:
            try:
                with psycopg.connect(**self.pg_options, dbname=os.getenv('PGDATABASE', 'postgres'), autocommit=True) as admin:
                    admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(self.source)))
            except Exception as error:
                errors.append(error)
        if errors:
            if original is not None:
                original.add_note('Cleanup errors: ' + '; '.join(map(str, errors)))
            else:
                raise ExceptionGroup('Could not clean all disposable databases', errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep', action='store_true', help='Retain this run’s databases for inspection')
    args = parser.parse_args()
    recipe = Recipe()
    success = False
    try:
        recipe.setup()
        recipe.pg.execute("INSERT INTO records(id,metric,payload) VALUES(2,20,'live')")
        wait_until(lambda: len(recipe.current()) == 2, 'live insert')
        print(json.dumps({'postgres_database': recipe.source, 'mirror_database': recipe.mirror,
                          'target_database': recipe.target, 'current': recipe.current()}, indent=2))
        success = True
    finally:
        if args.keep and success:
            recipe.pg.close()
        else:
            recipe.cleanup()


if __name__ == '__main__':
    main()
