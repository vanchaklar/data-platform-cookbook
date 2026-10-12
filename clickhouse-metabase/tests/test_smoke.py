"""Offline checks for probe behavior, failure paths and local safety boundaries."""

import base64
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("smoke", ROOT / "scripts" / "smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)
CONFIG = {"services": {
    "metabase-db": {"environment": {"POSTGRES_USER": "metabase", "POSTGRES_DB": "metabase"}},
    "clickhouse": {"environment": {"CLICKHOUSE_USER": "cookbook", "CLICKHOUSE_PASSWORD": "local-only"}},
}}


class EndpointTests(unittest.TestCase):
    def test_valid_loopback_binding(self):
        self.assertEqual(smoke.loopback_endpoint("127.0.0.1:38123\n"), "http://127.0.0.1:38123")

    def test_reject_external_malformed_and_multiple_bindings(self):
        for binding in ("", "0.0.0.0:8123", "example.org:8123", "[::]:8123",
                        "127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1:no",
                        "127.0.0.1:１２３", "127.0.0.1:1\n127.0.0.1:2"):
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                smoke.loopback_endpoint(binding)

    def test_endpoint_resolves_actual_ephemeral_port(self):
        with patch.object(smoke, "compose", return_value="127.0.0.1:54321") as command:
            self.assertEqual(smoke.endpoint("metabase", 3000), "http://127.0.0.1:54321")
        command.assert_called_once_with("port", "metabase", "3000")


class CommandTests(unittest.TestCase):
    def test_compose_scoped_checked_and_bounded(self):
        result = subprocess.CompletedProcess([], 0, stdout="  ok\n")
        with patch.object(smoke.subprocess, "run", return_value=result) as command:
            self.assertEqual(smoke.compose("config", "--format", "json"), "ok")
        command.assert_called_once_with(
            ["docker", "compose", "--file", str(ROOT / "compose.yaml"), "config", "--format", "json"],
            cwd=ROOT, text=True, check=True, capture_output=True, timeout=60,
        )

    def test_subprocess_failure_propagates(self):
        with patch.object(smoke.subprocess, "run", side_effect=subprocess.CalledProcessError(1, [])), \
                self.assertRaises(subprocess.CalledProcessError):
            smoke.compose("config", "--format", "json")


class HttpSafetyTests(unittest.TestCase):
    def test_read_bypasses_proxies_and_has_timeout(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(b"ok")
        request = urllib.request.Request("http://127.0.0.1:33000/api/health")
        with patch.object(smoke.urllib.request, "build_opener", return_value=opener) as build:
            self.assertEqual(smoke.read_local(request), b"ok")
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], smoke.NoRedirect)
        opener.open.assert_called_once_with(request, timeout=10)

    def test_redirects_are_disabled(self):
        self.assertIsNone(smoke.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.org/"))


class ServiceTests(unittest.TestCase):
    def test_postgres_uses_application_database_read_only_query(self):
        with patch.object(smoke, "compose", return_value="1") as command, patch("builtins.print"):
            smoke.check_postgres(CONFIG)
        command.assert_called_once_with(
            "exec", "-T", "metabase-db", "psql", "-X", "-U", "metabase", "-d", "metabase",
            "-At", "-v", "ON_ERROR_STOP=1", "-c", "SELECT 1",
        )

    def test_postgres_unexpected_result_fails(self):
        with patch.object(smoke, "compose", return_value="0"), self.assertRaisesRegex(RuntimeError, "PostgreSQL"):
            smoke.check_postgres(CONFIG)

    def test_clickhouse_authenticates_and_targets_warehouse(self):
        with patch.object(smoke, "endpoint", return_value="http://127.0.0.1:38123"), \
                patch.object(smoke, "read_local", return_value=b"1\n") as read, patch("builtins.print"):
            smoke.check_clickhouse(CONFIG)
        request = read.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:38123/?database=warehouse&query=SELECT%201")
        self.assertEqual(request.get_header("Authorization"), "Basic " + base64.b64encode(b"cookbook:local-only").decode())

    def test_clickhouse_unexpected_result_fails(self):
        with patch.object(smoke, "endpoint", return_value="http://127.0.0.1:38123"), \
                patch.object(smoke, "read_local", return_value=b"0\n"), self.assertRaisesRegex(RuntimeError, "ClickHouse"):
            smoke.check_clickhouse(CONFIG)

    def test_metabase_requires_ok_health_status(self):
        with patch.object(smoke, "endpoint", return_value="http://127.0.0.1:33000"), \
                patch.object(smoke, "read_local", return_value=b'{"status":"ok"}') as read, patch("builtins.print"):
            smoke.check_metabase()
        self.assertEqual(read.call_args.args[0].full_url, "http://127.0.0.1:33000/api/health")

    def test_metabase_bad_status_and_malformed_json_fail(self):
        for body in (b'{"status":"initializing"}', b'{}', b'[]', b'not json'):
            with self.subTest(body=body), patch.object(smoke, "endpoint", return_value="http://127.0.0.1:33000"), \
                    patch.object(smoke, "read_local", return_value=body), self.assertRaises((ValueError, RuntimeError)):
                smoke.check_metabase()

    def test_main_reports_service_checks_without_claiming_driver_success(self):
        with patch.object(smoke, "compose", return_value="{}"), \
                patch.object(smoke, "check_postgres") as postgres, \
                patch.object(smoke, "check_clickhouse") as clickhouse, \
                patch.object(smoke, "check_metabase") as metabase, patch("builtins.print") as output:
            smoke.main()
        postgres.assert_called_once_with({})
        clickhouse.assert_called_once_with({})
        metabase.assert_called_once_with()
        self.assertIn("manual Metabase-to-ClickHouse query check", output.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
