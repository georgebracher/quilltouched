"""Static KNOWN-state boundary lint.

AST-walks every module under ``api/`` and ``llm/`` and fails the build
when one imports the referee-grade state surface. The narrator/API side
may consume ONLY:

- the KnownState surface (``everquill_engine.views`` MINUS RefereeState),
- the engine service surface (beat.assess_or_execute/confirm,
  store.execute_command, resolver.resolve_intent/outcome_contract/
  contract_id/errors) — commands IN, contracts OUT,
- config/boot plumbing (db, migrate, world loader, clock.world_date,
  genesis/chargen builders).

What it may NEVER touch: ``RefereeState``, ``load_known_state``'s raw
fold inputs (``FoldState``/``fold_event``/the folds module), or the raw
Tier-1 image loader ``load_fold_state`` — those hand back true aptitudes
and entity hp.

KNOWN DEBT (frozen, exact-match): EMPTY since Sprint 2 wave 2 — the
Sprint-1 fold-state reads in api/main.py and api/bootstrap.py were
migrated to the KnownState surface + execute_command. The ratchet
mechanism stays: the test fails on any NEW referee import anywhere,
and fails if the debt list ever goes stale (it only turns one way).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINTED_DIRS = ("api", "llm")

#: Names that constitute the referee surface, wherever they are imported from.
FORBIDDEN_NAMES = {
    "RefereeState",
    "FoldState",
    "fold_event",
    "load_fold_state",
    "rebuild_projections",
    "fresh_reset",
    "canonical_projection_dump",
    "canonical_event_dump",
}

#: Modules that may not be imported at all (their whole surface is referee-grade).
FORBIDDEN_MODULES = {
    "everquill_engine.folds",
}

#: Frozen Sprint-1 debt: (relative file, imported name). Wave-2 wiring must
#: shrink this — additions are failures, removals require editing this set
#: in the same commit (the ratchet).
#: EMPTY since Sprint 2 wave 2: api/main.py and api/bootstrap.py were
#: migrated off load_fold_state (KnownState surface + execute_command only).
#: The ratchet stays so it can never grow again.
KNOWN_DEBT: set[tuple[str, str]] = set()


def _imports_of(path: Path) -> list[tuple[str, str]]:
    """[(module, name)] for every import in the file. Plain ``import x``
    yields (x, '*module*'); ``from m import n`` yields (m, n)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, "*module*"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                found.append((node.module, alias.name))
    return found


def _linted_files() -> list[Path]:
    files = []
    for directory in LINTED_DIRS:
        root = REPO_ROOT / directory
        if root.exists():
            files.extend(sorted(root.rglob("*.py")))
    return files


class TestKnownStateBoundary:
    def test_api_and_llm_never_import_the_referee_surface(self):
        violations = []
        debt_hits = set()
        for path in _linted_files():
            rel = str(path.relative_to(REPO_ROOT))
            for module, name in _imports_of(path):
                if module in FORBIDDEN_MODULES or (
                    module == "everquill_engine" and name in FORBIDDEN_MODULES
                ):
                    violations.append(f"{rel}: imports referee module {module!r}")
                    continue
                if name == "*":
                    violations.append(f"{rel}: wildcard import from {module!r}")
                    continue
                if name in FORBIDDEN_NAMES or (
                    name == "*module*" and module in FORBIDDEN_MODULES
                ):
                    if (rel, name) in KNOWN_DEBT:
                        debt_hits.add((rel, name))
                    else:
                        violations.append(
                            f"{rel}: imports referee-surface name {name!r} from "
                            f"{module!r} — consume the KnownState surface "
                            "(everquill_engine.views) instead"
                        )
        assert not violations, "KNOWN-state boundary violations:\n" + "\n".join(violations)
        # The ratchet: the debt list must match reality EXACTLY. When the API
        # removes a debt import, this line forces shrinking KNOWN_DEBT too.
        assert debt_hits == KNOWN_DEBT, (
            "KNOWN_DEBT is stale. Present debt imports: "
            f"{sorted(debt_hits)}; frozen list: {sorted(KNOWN_DEBT)} — "
            "shrink the list in tests/test_known_boundary.py (never grow it)"
        )

    def test_lint_actually_sees_the_api_modules(self):
        """Guard the guard: the walker must find real files with real
        engine imports, or the lint is vacuously green."""
        files = _linted_files()
        assert any(f.name == "main.py" for f in files)
        engine_imports = [
            (str(f), name)
            for f in files
            for module, name in _imports_of(f)
            if module.startswith("everquill_engine")
        ]
        assert engine_imports, "no engine imports found under api/ or llm/ — walker broken?"

    def test_referee_state_is_not_reexported_by_the_known_surface_docs(self):
        """views.py exports both classes (engine-internal callers need
        RefereeState), so the boundary is THIS lint — assert the names
        exist where the lint expects them."""
        from everquill_engine import views

        assert hasattr(views, "KnownState") and hasattr(views, "RefereeState")
        assert "RefereeState" in FORBIDDEN_NAMES
