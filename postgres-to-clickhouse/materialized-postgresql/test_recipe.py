import os
import unittest
from unittest.mock import Mock
from recipe import Recipe, range_size, literal, wait_until


class ConfigurationTests(unittest.TestCase):
    def test_range_size(self):
        self.assertEqual(range_size('1000000'), 1000000)
        for value in ('0', '-1', '1', '2', '3', 'abc', str(2**63)):
            with self.assertRaises(ValueError):
                range_size(value)

    def test_literal_escaping(self):
        self.assertEqual(literal("a'b\\c"), "'a\\'b\\\\c'")

    def test_cleanup_attempts_mirror_after_target_failure(self):
        r = Recipe()
        r.ch = Mock(side_effect=[RuntimeError('target drop failed'), None])
        with self.assertRaises(ExceptionGroup):
            r.cleanup()
        self.assertEqual(r.ch.call_count, 2)
        self.assertIn(r.mirror, r.ch.call_args.args[0])

    def test_cleanup_does_not_mask_original_error(self):
        r = Recipe()
        r.ch = Mock(side_effect=RuntimeError('drop failed'))
        original = ValueError('test failure')
        try:
            raise original
        except ValueError:
            r.cleanup()
        self.assertIn('Cleanup errors', original.__notes__[0])


@unittest.skipUnless(os.getenv('RUN_INTEGRATION') == '1', 'requires PostgreSQL and ClickHouse')
class ReplicationTests(unittest.TestCase):
    def test_snapshot_mutations_and_partition_identity(self):
        r = Recipe()
        try:
            r.setup()
            self.assertEqual(r.current(), [{'id': 1, 'metric': 10, 'payload': 'snapshot'}])
            r.pg.execute("INSERT INTO records(id,metric,payload) VALUES(2,20,'live')")
            wait_until(lambda: len(r.current()) == 2, 'live insert')
            r.pg.execute("UPDATE records SET metric=25,payload='updated',updated_at=now() WHERE id=2")
            wait_until(lambda: any(int(x['id']) == 2 and int(x['metric']) == 25 for x in r.current()), 'update')
            old = r.ch(f'SELECT max(version) FROM {r.target}.history WHERE id=2')
            r.pg.execute('DELETE FROM records WHERE id=2')
            wait_until(lambda: len(r.current()) == 1, 'delete')
            self.assertEqual(r.ch(f'SELECT count() FROM {r.target}.history WHERE id=2 AND is_deleted=1'), '1')
            r.ch(f"INSERT INTO {r.target}.current VALUES(2,20,'stale',now(),{old},0)")
            self.assertEqual(len(r.current()), 1, 'older replay must not resurrect deleted key')
            for key in (r.size - 1, r.size):
                r.pg.execute('INSERT INTO records(id,metric,payload) VALUES(%s,30,%s)', (key, 'boundary'))
            wait_until(lambda: len(r.current()) == 3, 'range boundary inserts')
            partitions = r.rows(f'SELECT DISTINCT _partition_id AS p FROM {r.target}.current WHERE id IN ({r.size-1},{r.size})')
            self.assertEqual(len(partitions), 2)
            r.pg.execute('UPDATE records SET id=%s WHERE id=%s', (r.size + 1, r.size - 1))
            wait_until(lambda: {int(x['id']) for x in r.current()} == {1, r.size, r.size + 1}, 'primary key change')
            r.pg.execute('ALTER TABLE records ADD COLUMN extra text NOT NULL DEFAULT \'untracked\'')
            r.pg.execute("INSERT INTO records(id,metric,payload) VALUES(%s,40,'after-ddl')", (r.size + 2,))
            wait_until(lambda: len(r.current()) == 4, 'explicit column list survives unrelated added column')
            self.assertEqual(r.ch(f"SELECT count() FROM system.columns WHERE database='{r.mirror}' AND table='records' AND name='extra'"), '0')
            self.assertGreaterEqual(int(r.ch(f'SELECT count() FROM {r.target}.history')), 9)
        finally:
            r.cleanup()


if __name__ == '__main__':
    unittest.main()
