"""
Layer 1 — Cross-source agreement.

Every key field must appear in 2+ independent occurrences with identical
values. The happy-path test confirms the committed PDFs satisfy this. The
fault-injection test corrupts one provenance hit and asserts the validator
raises.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import extract


def test_layer_1_passes_on_committed_inputs(
    inputs_dir: Path, golden_path: Path, tmp_path: Path
) -> None:
    """Happy path: committed PDFs pass Layer 1 cross-source agreement."""
    result = extract.extract_all(
        inputs_dir=inputs_dir,
        golden_path=golden_path,
        log_path=tmp_path / "log.json",
    )
    cross_source = result.validation["layer_1_cross_source"]
    assert cross_source, "Layer 1 must produce findings"
    assert all(entry["status"] == "PASS" for entry in cross_source), (
        f"Expected all PASS, got {[e for e in cross_source if e['status'] != 'PASS']}"
    )
    # Spot check: at least one field has hits from both PDFs (BAC + Cowen)
    bloom_27 = next(
        e for e in cross_source
        if e["field"] == "bloomberg_cy27_consensus_eps"
    )
    sources = {f for f, _ in bloom_27["pages"]}
    assert len(sources) >= 2, (
        f"Bloomberg CY27 EPS should have 2+ source files, got {sources}"
    )


def test_layer_1_raises_on_disagreeing_sources(
    inputs_dir: Path, golden_path: Path
) -> None:
    """Fault injection: forge a disagreeing hit; expect ValidationError."""
    result = extract.ExtractionResult()
    extract._extract_q1_pr(inputs_dir / "Q126_PR_5-4-26.pdf", result)
    extract._extract_bac(inputs_dir / "BAC__buy__5-5-26.pdf", result)
    extract._extract_cowen(inputs_dir / "COWN__hold__5-4-26.pdf", result)
    # Corrupt one provenance entry so two sources disagree
    bad = extract.NumberHit(
        field_name="bac_pt", value=999.99,
        source_file="forged", page=0, snippet="injected fault",
    )
    result.provenance["bac_pt"].append(bad)
    result.values["bac_pt"] = 999.99
    with pytest.raises(extract.ValidationError, match="sources disagree"):
        extract._layer_1_cross_source(result)
