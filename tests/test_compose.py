"""Compose files keep the stack off the LAN: only loopback ports, and the AI service and Redis stay
internal in the base file (spec D5)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILES = ["compose.yaml", "compose.dev.yaml", "compose.e2e.yaml"]
LOOPBACK = "127.0.0.1"


def services(name: str) -> dict[str, dict[str, Any]]:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))["services"]


def host_ip(port: str | int | dict[str, Any]) -> str | None:
    """Short syntax `[HOST_IP:]HOST:CONTAINER[/proto]`, or the long syntax's `host_ip`."""
    if isinstance(port, dict):
        return port.get("host_ip")
    parts = str(port).split(":")
    return parts[0] if len(parts) == 3 else None


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_published_ports_bind_to_loopback(name: str) -> None:
    published = {
        f"{service}: {port}": host_ip(port)
        for service, config in services(name).items()
        for port in config.get("ports", [])
    }
    exposed = [port for port, ip in published.items() if ip != LOOPBACK]
    assert not exposed, f"{name} publishes ports beyond {LOOPBACK}: {exposed}"


@pytest.mark.parametrize("service", ["ai-service", "redis"])
def test_internal_services_publish_nothing(service: str) -> None:
    assert "ports" not in services("compose.yaml")[service]


def test_web_is_published() -> None:
    assert services("compose.yaml")["web"]["ports"] == [f"{LOOPBACK}:3000:3000"]


def strings(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [s for key, value in node.items() for s in (*strings(key), *strings(value))]
    if isinstance(node, list):
        return [s for item in node for s in strings(item)]
    return [node] if isinstance(node, str) else []


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_no_host_shell_interpolation(name: str) -> None:
    """`${...}` would read the host shell (and its exported API keys) into the containers."""
    document = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
    assert not [s for s in strings(document) if "$" in s]
