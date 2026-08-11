"""Enforce the hexagonal layering rules with an import check.

Layers, inner to outer:
    domain -> application -> adapters -> infra/cli, tui

Rules:
- domain imports stdlib + todo.domain only.
- application imports stdlib + domain + application + exceptions only —
  never adapters, infra, tui, or third-party UI/storage libraries.
- adapters implement application contracts: no click/textual, no infra/tui.
- tui never imports infra; infra/cli is the composition root and may import
  anything (including tui, for the `todo ui` command).
- config and exceptions are dependency-free leaves (stdlib only).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "todo"

_STDLIB = set(sys.stdlib_module_names)

# layer -> (allowed third-party roots, allowed todo.* prefixes)
_RULES: dict[str, tuple[set[str], set[str]]] = {
    "domain": (set(), {"todo.domain"}),
    "application": (
        set(),
        {"todo.domain", "todo.application", "todo.exceptions"},
    ),
    "adapters": (
        {"rich"},
        {
            "todo.domain",
            "todo.application",
            "todo.exceptions",
            "todo.adapters",
            "todo.config",
        },
    ),
    "tui": (
        {"rich", "textual"},
        {
            "todo.domain",
            "todo.application",
            "todo.exceptions",
            "todo.adapters",
            "todo.config",
            "todo.tui",
        },
    ),
    "infra": ({"click", "rich", "textual"}, {"todo"}),
    "root": (set(), {"todo.exceptions", "todo.config"}),
}


def _layer_of(path: Path) -> str:
    rel = path.relative_to(SRC)
    return rel.parts[0] if len(rel.parts) > 1 else "root"


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def _violations_for(path: Path) -> list[str]:
    layer = _layer_of(path)
    third_party_ok, todo_ok = _RULES[layer]
    violations: list[str] = []
    for module in _imported_modules(path):
        root = module.split(".")[0]
        if root == "todo":
            if not any(
                module == p or module.startswith(f"{p}.") for p in todo_ok
            ):
                violations.append(module)
        elif root not in _STDLIB and root not in third_party_ok:
            violations.append(module)
    return violations


class TestArchitecture:
    def test_source_tree_is_where_we_think(self) -> None:
        assert SRC.is_dir()
        assert (SRC / "domain").is_dir()

    def test_layer_import_rules(self) -> None:
        offenders: dict[str, list[str]] = {}
        for path in sorted(SRC.rglob("*.py")):
            violations = _violations_for(path)
            if violations:
                offenders[str(path.relative_to(SRC))] = violations
        assert not offenders, f"Layer rule violations: {offenders}"

    def test_every_module_is_covered_by_a_rule(self) -> None:
        for path in SRC.rglob("*.py"):
            assert _layer_of(path) in _RULES, f"No layer rule for {path}"
