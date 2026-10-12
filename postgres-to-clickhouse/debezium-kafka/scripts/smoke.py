"""Infrastructure smoke checks only: no connector registration or CDC data flow."""

import base64
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "--file", str(ROOT / "compose.yaml")]
POSTGRES_PLUGIN = "io.debezium.connector.postgresql.PostgresConnector"


def run(*args, input_text=None, timeout=60):
    """Run a bounded command and retain stderr in any raised exception."""
    return subprocess.run(
        args, input=input_text, text=True, check=True, capture_output=True,
        timeout=timeout, cwd=ROOT,
    ).stdout.strip()


def compose(*args, **kwargs):
    return run(*COMPOSE, *args, **kwargs)


def compose_exec(service, *args, **kwargs):
    options = ["-e", "KAFKA_HEAP_OPTS=-Xms64m -Xmx128m"] if service == "kafka" else []
    return compose("exec", "-T", *options, service, *args, **kwargs)


def loopback_endpoint(binding):
    """Require a single IPv4 loopback binding, including ephemeral test ports."""
    host, separator, port = binding.strip().rpartition(":")
    if separator != ":" or host != "127.0.0.1" or not port.isdigit():
        raise ValueError(f"Expected a loopback host:port binding, got {binding!r}")
    if not 1 <= int(port) <= 65535:
        raise ValueError(f"Invalid published port: {port}")
    return f"http://{host}:{port}"


def endpoint(service, target):
    # `config` contains published=0 in disposable tests; ask Docker for the actual port.
    return loopback_endpoint(compose("port", service, str(target)))


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def wait_for(label, check, timeout=60):
    deadline = time.monotonic() + timeout
    last_error = "unexpected response"
    while time.monotonic() < deadline:
        try:
            if check():
                print(f"PASS {label}", flush=True)
                return
            last_error = "unexpected response"
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            last_error = type(error).__name__
        time.sleep(2)
    raise TimeoutError(f"{label} did not become ready: {last_error}")


def check_postgres(config):
    pg = config["services"]["postgres"]["environment"]
    result = compose_exec(
        "postgres", "psql", "-X", "-U", pg["POSTGRES_USER"], "-d", pg["POSTGRES_DB"],
        "-At", "-v", "ON_ERROR_STOP=1", "-c", "SELECT 1; SHOW wal_level;",
    )
    if result.splitlines() != ["1", "logical"]:
        raise RuntimeError("PostgreSQL SQL/logical replication check failed")
    print("PASS PostgreSQL SQL and logical WAL", flush=True)


def check_clickhouse(config):
    ch = config["services"]["clickhouse"]["environment"]
    request = urllib.request.Request(endpoint("clickhouse", 8123) + "/?query=SELECT%201")
    credential = f"{ch['CLICKHOUSE_USER']}:{ch['CLICKHOUSE_PASSWORD']}".encode()
    request.add_header("Authorization", "Basic " + base64.b64encode(credential).decode())
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.read().strip() != b"1":
            raise RuntimeError("ClickHouse SQL check failed")
    print("PASS ClickHouse authenticated HTTP SQL", flush=True)


def check_connect():
    connect = endpoint("connect", 8083)
    wait_for("Debezium PostgreSQL plugin", lambda: any(
        plugin.get("class") == POSTGRES_PLUGIN
        for plugin in get_json(connect + "/connector-plugins")
    ))


def check_kafka():
    # Own a uniquely named temporary topic; never read or remove application topics.
    topic = "cookbook-smoke-" + uuid.uuid4().hex
    message = "infrastructure-smoke-" + uuid.uuid4().hex
    cli = "/opt/kafka/bin/"
    created = False
    try:
        compose_exec(
            "kafka", cli + "kafka-topics.sh", "--bootstrap-server", "kafka:9092",
            "--create", "--topic", topic, "--partitions", "1", "--replication-factor", "1",
        )
        created = True
        compose_exec(
            "kafka", cli + "kafka-console-producer.sh", "--bootstrap-server", "kafka:9092",
            "--topic", topic, "--producer-property", "acks=all", input_text=message + "\n",
        )
        received = compose_exec(
            "kafka", cli + "kafka-console-consumer.sh", "--bootstrap-server", "kafka:9092",
            "--topic", topic, "--partition", "0", "--offset", "earliest",
            "--max-messages", "1", "--timeout-ms", "20000",
        )
        if received != message:
            raise RuntimeError("Kafka roundtrip returned an unexpected message")
        print("PASS Kafka produce/consume roundtrip", flush=True)
    finally:
        if created:
            compose_exec(
                "kafka", cli + "kafka-topics.sh", "--bootstrap-server", "kafka:9092",
                "--delete", "--topic", topic,
            )


def main():
    config = json.loads(compose("config", "--format", "json"))
    check_postgres(config)
    check_clickhouse(config)
    check_connect()
    check_kafka()
    print("Infrastructure smoke checks passed. No end-to-end CDC is configured or tested.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        # Keep command diagnostics visible without echoing credential arguments.
        if error.stderr:
            print(error.stderr, flush=True)
        raise
