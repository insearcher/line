from __future__ import annotations

from importlib import import_module
from pathlib import Path


def test_line_package_is_public_import_namespace() -> None:
    package = import_module("line")

    assert package.main is not None


def test_working_tree_does_not_contain_old_project_names() -> None:
    forbidden = (
        "_".join(("codex", "voice", "mvp")),
        "_".join(("codex", "voice")),
        "-".join(("codex", "voice", "mvp")),
        "-".join(("codex", "voice")),
        "".join(("Codex", "Voice")),
        " ".join(("Codex", "Voice")),
    )
    offenders = _find_forbidden_tokens(forbidden)

    assert offenders == []


def test_working_tree_does_not_contain_dummy_secret_values() -> None:
    forbidden = (
        "-".join(("local", "secret")),
        "_".join(("lk", "secret")),
        "_".join(("dg", "key")),
        "_".join(("xi", "key")),
        "dev" + "key",
        "replace" + "-me",
        "Bearer " + "secret",
    )
    offenders = _find_forbidden_tokens(forbidden)

    assert offenders == []


def _find_forbidden_tokens(forbidden: tuple[str, ...]) -> list[str]:
    root = Path(__file__).resolve().parents[1]
    skipped_dirs = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "data",
        "logs",
        "node_modules",
        "xcuserdata",
    }
    skipped_files = {".env"}

    offenders: list[str] = []
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if any(part in skipped_dirs for part in relative_parts):
            continue
        if path.name in skipped_files:
            continue
        relative = "/".join(relative_parts)
        if any(token in relative for token in forbidden):
            offenders.append(relative)
            continue
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            if token in content:
                offenders.append(f"{relative}: {token}")
                break

    return offenders
