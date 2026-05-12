"""Shared fixtures for the validation-layer tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def inputs_dir() -> Path:
    """Path to the committed inputs directory with PDFs and golden.json."""
    return ROOT / "inputs"


@pytest.fixture(scope="session")
def golden_path(inputs_dir: Path) -> Path:
    """Path to inputs/golden.json — the Layer 3 baseline."""
    return inputs_dir / "golden.json"
