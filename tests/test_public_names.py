from __future__ import annotations

from importlib import import_module
from pathlib import Path
import re


def test_line_package_is_public_import_namespace() -> None:
    package = import_module("line")

    assert package.main is not None


def test_working_tree_does_not_contain_old_project_names() -> None:
    forbidden = (
        "_".join(("codex", "voice", "mvp")),
        "_".join(("codex", "voice")),
        "-".join(("codex", "voice", "mvp")),
        "-".join(("codex", "voice")),
        "-".join(("Codex", "Voice")),
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


def test_working_tree_does_not_contain_local_personal_values() -> None:
    forbidden = (
        "frol" + "ov",
        "mak" + "sim",
        "mp" + "frol" + "ov",
        "in" + "searcher",
        "213" + "64249",
        "HMZ" + "53E86L8",
        "com.max" + "im",
        "X-" + "Codex" + "-Voice-Token",
    )
    offenders = _find_forbidden_tokens(forbidden, ignore_case=True)

    assert offenders == []


def test_working_tree_does_not_contain_cyrillic_text() -> None:
    offenders = _find_forbidden_pattern(re.compile(r"[\u0400-\u04FF]"))

    assert offenders == []


def _find_forbidden_tokens(forbidden: tuple[str, ...], *, ignore_case: bool = False) -> list[str]:
    root = Path(__file__).resolve().parents[1]
    search_tokens = tuple(token.lower() for token in forbidden) if ignore_case else forbidden
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
        searchable_relative = relative.lower() if ignore_case else relative
        if any(token in searchable_relative for token in search_tokens):
            offenders.append(relative)
            continue
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="ignore")
        searchable_content = content.lower() if ignore_case else content
        for token, display_token in zip(search_tokens, forbidden, strict=True):
            if token in searchable_content:
                offenders.append(f"{relative}: {display_token}")
                break

    return offenders


def _find_forbidden_pattern(pattern: re.Pattern[str]) -> list[str]:
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
        if path.name in skipped_files or not path.is_file():
            continue
        relative = "/".join(relative_parts)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="ignore")
        match = pattern.search(content)
        if match is not None:
            offenders.append(f"{relative}: {match.group(0)!r}")

    return offenders
