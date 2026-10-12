"""Read-only service checks; Metabase's ClickHouse driver is checked manually."""

import base64
import json
from pathlib import Path
import subprocess
import sys
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "--file", str(ROOT / "compose.yaml")]


def compose(*args):
    return subprocess.run(
        [*COMPOSE, *args], cwd=ROOT, text=True, check=True,
        capture_output=True, timeout=60,
    ).stdout.strip()


def loopback_endpoint(binding):
    """Accept only a single IPv4 loopback binding returned by Compose."""
    host, _, port = binding.strip().rpartition(":")
    if host != "127.0.0.1" or not port.isascii() or not port.isdigit():
        raise ValueError("Expected a single 127.0.0.1:port binding")
    if not 1 <= int(port) <= 65535:
        raise ValueError("Published port must be between 1 and 65535")
    return f"http://{host}:{port}"


def endpoint(service, target):
    # Resolve actual ports so disposable tests can use ephemeral host ports.
    return loopback_endpoint(compose("port", service, str(target)))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward development credentials to a redirected destination.
        return None


def read_local(request):
    # Loopback probes must bypass environment-configured HTTP proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=10) as response:
        return response.read()


def check_postgres(config):
    pg = config["services"]["metabase-db"]["environment"]
    result = compose(
        "exec", "-T", "metabase-db", "psql", "-X", "-U", pg["POSTGRES_USER"],
        "-d", pg["POSTGRES_DB"], "-At", "-v", "ON_ERROR_STOP=1", "-c", "SELECT 1",
    )
    if result != "1":
        raise RuntimeError("PostgreSQL application database SQL check failed")
    print("PASS PostgreSQL application database SQL", flush=True)


def check_clickhouse(config):
    ch = config["services"]["clickhouse"]["environment"]
    request = urllib.request.Request(endpoint("clickhouse", 8123) + "/?database=warehouse&query=SELECT%201")
    credential = f"{ch['CLICKHOUSE_USER']}:{ch['CLICKHOUSE_PASSWORD']}".encode()
    request.add_header("Authorization", "Basic " + base64.b64encode(credential).decode())
    if read_local(request).strip() != b"1":
        raise RuntimeError("ClickHouse authenticated HTTP SQL check failed")
    print("PASS ClickHouse authenticated HTTP SQL in warehouse", flush=True)


def check_metabase():
    request = urllib.request.Request(endpoint("metabase", 3000) + "/api/health")
    result = json.loads(read_local(request))
    if not isinstance(result, dict) or result.get("status") != "ok":
        raise RuntimeError("Metabase health check failed")
    print("PASS Metabase health endpoint", flush=True)


def main():
    config = json.loads(compose("config", "--format", "json"))
    check_postgres(config)
    check_clickhouse(config)
    check_metabase()
    print("Service checks passed. Complete the README's manual Metabase-to-ClickHouse query check.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # Do not print resolved Compose configuration or credentials.
        print(f"Service checks failed ({type(error).__name__}). Inspect make logs.", file=sys.stderr)
        sys.exit(1)
