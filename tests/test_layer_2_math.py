"""
Layer 2 — Math reconstruction.

Asserts PT ~= EPS*PE within 2 percent, printed YoY EPS reconstructs from the
EPS series within 0.1pp, and year-indexed series are monotone increasing.
Fault-injection breaks the monotone property and confirms the abort.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import extract


def test_layer_2_passes_on_committed_inputs(
    inputs_dir: Path, golden_path: Path, tmp_path: Path
) -> None:
    """Happy path: PT ~= EPS*PE; YoY reconstructs; series monotone."""
    result = extract.extract_all(
        inputs_dir=inputs_dir,
        golden_path=golden_path,
        log_path=tmp_path / "log.json",
    )
    math = result.validation["layer_2_math"]
    assert math, "Layer 2 must produce findings"
    assert all(entry["status"] == "PASS" for entry in math), (
        f"Expected all PASS, got {[e for e in math if e['status'] != 'PASS']}"
    )
    # Confirm the specific check we care about most
    pt_checks = [e for e in math if "PT" in e["check"]]
    assert len(pt_checks) == 2, "Expected BAC + Cowen PT checks"
    for entry in pt_checks:
        assert entry["drift_pct"] <= 2.0, f"PT drift exceeded 2%: {entry}"


def test_layer_2_raises_on_non_monotone_series(
    inputs_dir: Path, golden_path: Path
) -> None:
    """Fault injection: shuffle EPS series; expect ValidationError."""
    result = extract.ExtractionResult()
    extract._extract_q1_pr(inputs_dir / "Q126_PR_5-4-26.pdf", result)
    extract._extract_bac(inputs_dir / "BAC__buy__5-5-26.pdf", result)
    extract._extract_cowen(inputs_dir / "COWN__hold__5-4-26.pdf", result)
    # Break the EPS series ordering so Layer 2's monotone check fails
    result.bac_eps_by_year["2027E"] = 5.00  # below 2026E (9.36)
    with pytest.raises(extract.ValidationError, match="(?i)(monotone|drift)"):
        extract._layer_2_math(result)
