"""
Loads pre-generated qualitative content from outputs/qualitative.json. No API
calls. Generation is upstream of this module — see README "Refreshing the
qualitative section" for how to regenerate when analyst PDFs change.

If outputs/qualitative.json is missing, returns None. run.py prints a warning
and memo.py renders the brief without the analyst-rationale sections.

Soft check: each bullet is scanned for at least one AEIS-specific whitelist
token. Failing bullets are tagged with REVIEW in the brief, not removed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


AEIS_WHITELIST = [
    "DC", "data center", "semi", "WFE", "800V", "Kyber", "PECVD",
    "eVoS", "eVerest", "NavX", "AMAT", "LRCX", "Artesyn",
    "Industrial", "Telecom", "margin", "Q1", "Q2", "guide", "CY26", "CY27",
]


@dataclass
class QualitativeResult:
    analyst: str
    source_file: str
    bull_case_reasons: list[str] = field(default_factory=list)
    bear_case_reasons: list[str] = field(default_factory=list)
    key_debate_flagged: str = ""
    catalysts: list[str] = field(default_factory=list)
    review_flags: dict[str, list[int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize this result for downstream consumers (memo, JSON dump)."""
        return {
            "analyst": self.analyst,
            "source_file": self.source_file,
            "bull_case_reasons": self.bull_case_reasons,
            "bear_case_reasons": self.bear_case_reasons,
            "key_debate_flagged": self.key_debate_flagged,
            "catalysts": self.catalysts,
            "review_flags": self.review_flags,
        }


def _whitelist_review(bullets: list[str]) -> list[int]:
    """Indices of bullets that contain no whitelist token."""
    out: list[int] = []
    for idx, bullet in enumerate(bullets):
        text = bullet.lower()
        if not any(tok.lower() in text for tok in AEIS_WHITELIST):
            out.append(idx)
    return out


def _build(analyst: str, payload: dict, default_source: str) -> QualitativeResult:
    """Construct a QualitativeResult from a flat JSON payload + whitelist scan."""
    bull = payload.get("bull_case_reasons", []) or []
    bear = payload.get("bear_case_reasons", []) or []
    cats = payload.get("catalysts", []) or []
    return QualitativeResult(
        analyst=analyst,
        source_file=payload.get("source_file", default_source),
        bull_case_reasons=bull,
        bear_case_reasons=bear,
        key_debate_flagged=payload.get("key_debate_flagged", ""),
        catalysts=cats,
        review_flags={
            "bull_case_reasons": _whitelist_review(bull),
            "bear_case_reasons": _whitelist_review(bear),
            "catalysts": _whitelist_review(cats),
        },
    )


def run(inputs_dir: Path,
        cache_path: Path) -> Optional[dict[str, QualitativeResult]]:
    """
    Load qualitative content from cache_path. Returns None if missing so the
    caller can skip the qualitative sections cleanly.
    """
    if not cache_path.exists():
        return None
    data = json.loads(cache_path.read_text())
    out: dict[str, QualitativeResult] = {}
    for analyst_key, default_src in [
        ("bac", "BAC__buy__5-5-26.pdf"),
        ("cowen", "COWN__hold__5-4-26.pdf"),
    ]:
        payload = data.get(analyst_key)
        if not payload:
            continue
        # Tolerate the older wrapped cache format {cache_key, payload, ...}
        if isinstance(payload, dict) and "payload" in payload and "cache_key" in payload:
            payload = payload["payload"]
        out[analyst_key] = _build(analyst_key, payload, default_src)
    return out if out else None
