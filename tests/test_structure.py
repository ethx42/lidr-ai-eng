import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_PATHS = [
    "app/__init__.py",
    "app/main.py",
    "app/config.py",
    "app/routers/__init__.py",
    "app/routers/estimations.py",
    "app/services/__init__.py",
    "app/services/llm_service.py",
    "app/context/__init__.py",
    "app/context/examples.py",
    ".env.example",
    ".gitignore",
    "pyproject.toml",
    "README.md",
]

KEY_PATTERN = re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603, S607


@pytest.mark.parametrize("path", REQUIRED_PATHS)
def test_required_path_exists(path: str) -> None:
    assert (ROOT / path).is_file(), f"missing required file: {path}"


def test_env_is_git_ignored() -> None:
    assert git("check-ignore", "-q", ".env").returncode == 0


def test_key_pattern_detects_keys() -> None:
    fake_key = "sk-" + "proj-" + "a1B2" * 10
    assert KEY_PATTERN.search(f"OPENAI_API_KEY={fake_key}")
    assert not KEY_PATTERN.search("OPENAI_API_KEY=")


def test_no_api_keys_in_repo_files() -> None:
    files = git("ls-files", "--cached", "--others", "--exclude-standard").stdout.splitlines()
    leaks = [
        f
        for f in files
        if (ROOT / f).is_file() and KEY_PATTERN.search((ROOT / f).read_text(errors="ignore"))
    ]
    assert not leaks, f"API key-shaped strings found in: {leaks}"
