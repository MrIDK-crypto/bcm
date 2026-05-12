"""
Layer 3 — Golden tripwires.

Every extracted value must match inputs/golden.json exactly. Fault injection
drifts one extracted value and confirms the abort.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import extract


def test_layer_3_passes_on_committed_inputs(
    inputs_dir: Path, golden_path: Path, tmp_path: Path
) -> None:
    """Happy path: 15/15 golden values match extracted values."""
    result = extract.extract_all(
        inputs_dir=inputs_dir,
        golden_path=golden_path,
        log_path=tmp_path / "log.json",
    )
    golden = result.validation["layer_3_golden"]
    assert golden, "Layer 3 must produce findings"
    failures = [e for e in golden if e["status"] != "PASS"]
    assert not failures, f"Layer 3 failures: {failures}"
    assert len(golden) == 15, f"Expected 15 golden fields, got {len(golden)}"


def test_layer_3_raises_on_drift(
    inputs_dir: Path, golden_path: Path, tmp_path: Path
) -> None:
    """Fault injection: drift one extracted value; expect ValidationError."""
    result = extract.ExtractionResult()
    extract._extract_q1_pr(inputs_dir / "Q126_PR_5-4-26.pdf", result)
    extract._extract_bac(inputs_dir / "BAC__buy__5-5-26.pdf", result)
    extract._extract_cowen(inputs_dir / "COWN__hold__5-4-26.pdf", result)
    # Inject drift in one field
    result.values["bac_pt"] = 420.00  # golden says 430.00
    with pytest.raises(extract.ValidationError, match="bac_pt"):
        extract._layer_3_golden(result, golden_path)


def test_layer_3_raises_on_null_golden_slot(
    inputs_dir: Path, tmp_path: Path
) -> None:
    """Pipeline refuses to run when golden.json has null slots."""
    bad_golden = tmp_path / "golden.json"
    bad_golden.write_text(json.dumps({
        "q1_revenue_usd_m": None,
        "current_price_may_4": 387.03,
    }))
    result = extract.ExtractionResult()
    result.values = {"q1_revenue_usd_m": 511.0, "current_price_may_4": 387.03}
    with pytest.raises(extract.ValidationError, match="null slots"):
        extract._layer_3_golden(result, bad_golden)
