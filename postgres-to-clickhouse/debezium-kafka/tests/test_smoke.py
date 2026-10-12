"""Offline tests for safety boundaries and smoke-check failure behavior."""

import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "scripts" / "smoke.py"
SPEC = importlib.util.spec_from_file_location("smoke", MODULE)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class EndpointTests(unittest.TestCase):
    def test_loopback_binding(self):
        self.assertEqual(smoke.loopback_endpoint("127.0.0.1:32123\n"), "http://127.0.0.1:32123")

    def test_invalid_or_external_bindings_are_rejected(self):
        for binding in ["0.0.0.0:8123", "example.org:80", "127.0.0.1:0", "127.0.0.1:65536",
                        "127.0.0.1:no", "", "127.0.0.1:123\n127.0.0.1:456"]:
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                smoke.loopback_endpoint(binding)

    def test_endpoint_uses_runtime_port(self):
        with patch.object(smoke, "compose", return_value="127.0.0.1:32123") as command:
            self.assertEqual(smoke.endpoint("clickhouse", 8123), "http://127.0.0.1:32123")
        command.assert_called_once_with("port", "clickhouse", "8123")


class CommandTests(unittest.TestCase):
    def test_compose_is_scoped_to_this_recipe(self):
        with patch.object(smoke, "run", return_value="ok") as command:
            self.assertEqual(smoke.compose("config", "--quiet"), "ok")
        command.assert_called_once_with(
            "docker", "compose", "--file", str(MODULE.parent.parent / "compose.yaml"),
            "config", "--quiet",
        )

    def test_kafka_cli_has_bounded_heap_and_no_tty(self):
        with patch.object(smoke, "compose") as command:
            smoke.compose_exec("kafka", "probe", input_text="message\n")
        command.assert_called_once_with(
            "exec", "-T", "-e", "KAFKA_HEAP_OPTS=-Xms64m -Xmx128m", "kafka", "probe",
            input_text="message\n",
        )

    def test_subprocess_is_checked_and_bounded(self):
        completed = subprocess.CompletedProcess([], 0, stdout="  result\n")
        with patch.object(smoke.subprocess, "run", return_value=completed) as command:
            self.assertEqual(smoke.run("probe", timeout=12), "result")
        self.assertTrue(command.call_args.kwargs["check"])
        self.assertEqual(command.call_args.kwargs["timeout"], 12)
        self.assertEqual(command.call_args.kwargs["cwd"], MODULE.parent.parent)


class ReadinessTests(unittest.TestCase):
    def test_transient_failure_is_retried(self):
        with patch.object(smoke.time, "sleep"), patch("builtins.print"), \
                patch.object(smoke.time, "monotonic", side_effect=[0, 1, 2]):
            from unittest.mock import Mock
            check = Mock(side_effect=[OSError("not ready"), True])
            smoke.wait_for("service", check, timeout=10)
        self.assertEqual(check.call_count, 2)

    def test_timeout_fails(self):
        with patch.object(smoke.time, "sleep"), \
                patch.object(smoke.time, "monotonic", side_effect=[0, 1, 11]), \
                self.assertRaisesRegex(TimeoutError, "service did not become ready"):
            smoke.wait_for("service", lambda: False, timeout=10)


class ServiceChecksTests(unittest.TestCase):
    def test_postgres_requires_logical_wal(self):
        config = {"services": {"postgres": {"environment": {
            "POSTGRES_USER": "cookbook", "POSTGRES_DB": "source",
        }}}}
        with patch.object(smoke, "compose_exec", return_value="1\nreplica"), \
                self.assertRaisesRegex(RuntimeError, "logical replication"):
            smoke.check_postgres(config)

    def test_clickhouse_authentication_and_response(self):
        config = {"services": {"clickhouse": {"environment": {
            "CLICKHOUSE_USER": "cookbook", "CLICKHOUSE_PASSWORD": "local-only",
        }}}}
        with patch.object(smoke, "endpoint", return_value="http://127.0.0.1:28123"), \
                patch.object(smoke.urllib.request, "urlopen", return_value=io.BytesIO(b"1\n")) as urlopen, \
                patch("builtins.print"):
            smoke.check_clickhouse(config)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:28123/?query=SELECT%201")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))

    def test_clickhouse_wrong_result_fails(self):
        config = {"services": {"clickhouse": {"environment": {
            "CLICKHOUSE_USER": "cookbook", "CLICKHOUSE_PASSWORD": "local-only",
        }}}}
        with patch.object(smoke, "endpoint", return_value="http://127.0.0.1:28123"), \
                patch.object(smoke.urllib.request, "urlopen", return_value=io.BytesIO(b"0\n")), \
                self.assertRaisesRegex(RuntimeError, "ClickHouse SQL check failed"):
            smoke.check_clickhouse(config)

    def test_connect_checks_plugin_without_registering_connector(self):
        with patch.object(smoke, "endpoint", return_value="http://127.0.0.1:28083"), \
                patch.object(smoke, "get_json", return_value=[{"class": smoke.POSTGRES_PLUGIN}]) as get, \
                patch("builtins.print"):
            smoke.check_connect()
        get.assert_called_once_with("http://127.0.0.1:28083/connector-plugins")


class KafkaChecksTests(unittest.TestCase):
    def test_roundtrip_uses_and_cleans_only_its_topic(self):
        calls = []
        def fake_exec(*args, **kwargs):
            calls.append((args, kwargs))
            if "kafka-console-consumer.sh" in args[1]:
                return calls[1][1]["input_text"].strip()
            return ""
        with patch.object(smoke, "compose_exec", side_effect=fake_exec), patch("builtins.print"):
            smoke.check_kafka()
        self.assertEqual(len(calls), 4)
        topic = calls[0][0][calls[0][0].index("--topic") + 1]
        self.assertTrue(topic.startswith("cookbook-smoke-"))
        self.assertIn("--create", calls[0][0])
        self.assertIn("--delete", calls[-1][0])
        for args, _ in calls:
            self.assertEqual(args[args.index("--topic") + 1], topic)

    def test_roundtrip_mismatch_still_deletes_topic(self):
        with patch.object(smoke, "compose_exec", side_effect=["", "", "wrong", ""]) as command, \
                self.assertRaisesRegex(RuntimeError, "unexpected message"):
            smoke.check_kafka()
        self.assertIn("--delete", command.call_args.args)

    def test_failed_create_does_not_delete_topic(self):
        with patch.object(smoke, "compose_exec", side_effect=subprocess.CalledProcessError(1, [])) as command, \
                self.assertRaises(subprocess.CalledProcessError):
            smoke.check_kafka()
        self.assertEqual(command.call_count, 1)


if __name__ == "__main__":
    unittest.main()
