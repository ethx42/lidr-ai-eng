"""Compose files keep the stack off the LAN and the keys in one place (spec D5): loopback-only
ports, the AI service and Redis internal, API keys only in the AI service, and an offline e2e stack
that never receives a real key."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILES = ["compose.yaml", "compose.dev.yaml", "compose.e2e.yaml"]
LOOPBACK = "127.0.0.1"

type YAML = Any  # yaml.load returns untyped data; tests index into it freely


@dataclass(frozen=True)
class Tagged:
    """A value under a Compose merge tag: `!reset` clears the base file's value, `!override`
    replaces it (a plain value would be merged with the base instead)."""

    tag: str
    value: YAML


class ComposeLoader(yaml.SafeLoader):
    pass


def construct_tagged(loader: yaml.SafeLoader, node: yaml.Node) -> Tagged:
    if isinstance(node, yaml.SequenceNode):
        return Tagged(node.tag, loader.construct_sequence(node, deep=True))
    if isinstance(node, yaml.MappingNode):
        return Tagged(node.tag, loader.construct_mapping(node, deep=True))
    return Tagged(node.tag, loader.construct_scalar(node))


for merge_tag in ("!reset", "!override"):
    ComposeLoader.add_constructor(merge_tag, construct_tagged)


def services(name: str) -> dict[str, YAML]:
    text = (ROOT / name).read_text(encoding="utf-8")
    document = yaml.load(text, ComposeLoader)  # noqa: S506  # a SafeLoader with data-only tags
    return document["services"]


def host_ip(port: YAML) -> str | None:
    """Short syntax `[HOST_IP:]HOST:CONTAINER[/proto]`, or the long syntax's `host_ip`."""
    if isinstance(port, dict):
        return port.get("host_ip")
    parts = str(port).split(":")
    return parts[0] if len(parts) == 3 else None


def strings(node: YAML) -> list[str]:
    if isinstance(node, Tagged):
        return strings(node.value)
    if isinstance(node, dict):
        return [s for key, value in node.items() for s in (*strings(key), *strings(value))]
    if isinstance(node, list):
        return [s for item in node for s in strings(item)]
    return [node] if isinstance(node, str) else []


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_published_ports_bind_to_loopback(name: str) -> None:
    published = {
        f"{service}: {port}": host_ip(port)
        for service, config in services(name).items()
        for port in config.get("ports", [])
    }
    exposed = [port for port, ip in published.items() if ip != LOOPBACK]
    assert not exposed, f"{name} publishes ports beyond {LOOPBACK}: {exposed}"


def test_only_web_is_published_in_the_base_file() -> None:
    base = services("compose.yaml")
    assert base["web"]["ports"] == [f"{LOOPBACK}:3000:3000"]
    assert "ports" not in base["ai-service"]


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_redis_is_never_published(name: str) -> None:
    assert "ports" not in services(name).get("redis", {})


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_only_the_ai_service_reads_env_files(name: str) -> None:
    readers = [service for service, config in services(name).items() if "env_file" in config]
    assert set(readers) <= {"ai-service"}, f"{name}: {readers} read env files (API keys)"


def test_e2e_stack_is_offline_and_keyless() -> None:
    ai_service = services("compose.e2e.yaml")["ai-service"]
    assert ai_service["env_file"] == Tagged("!reset", [])
    assert ai_service["environment"] == {
        "LLM_PROVIDER": "replay",
        "LLM_FALLBACKS": "none",
        "REDIS_URL": "",
    }
    assert "./tests/cassettes:/app/tests/cassettes:ro" in ai_service["volumes"]


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_no_host_shell_interpolation(name: str) -> None:
    """`${...}` would read the host shell (and its exported API keys) into the containers."""
    assert not [s for s in strings(services(name)) if "$" in s]
