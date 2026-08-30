"""Control-plane hygiene gates that must stay green from day one."""

from __future__ import annotations

from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "ylang"


def test_litellm_completion_only_in_engine() -> None:
    """CP-G-01: faces must not call LiteLLM; only Engine may invoke completion."""
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "litellm.completion" not in text and "litellm.acompletion" not in text:
            continue
        rel = path.relative_to(_SRC)
        if rel.as_posix() != "core/engine.py":
            offenders.append(str(rel))
    assert offenders == [], f"LiteLLM completion outside Engine: {offenders}"
