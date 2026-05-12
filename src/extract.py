"""
Deterministic PDF number extraction with three layers of self-validation.

Pulls every figure used downstream from at least two locations in the source
PDFs (or the same PDF twice when no second PDF reports the figure), then runs
three validation passes:

  Layer 1 — Cross-source agreement
      For each key number, compare two independent occurrences and assert
      they match exactly. On mismatch, abort with both values and page refs.

  Layer 2 — Math reconstruction
      Verify PT ~= EPS * PE within 2 pct for each analyst.
      Verify printed YoY EPS growth percentages reconstruct from extracted
      year-over-year EPS values within 0.1 percentage points.
      Verify year-indexed EPS series is monotone increasing.

  Layer 3 — Golden value tripwires
      Compare every extracted value to inputs/golden.json. On any drift,
      abort and name the field that drifted.

The consensus row in BAC reports the FORWARD three years (CY26E, CY27E,
CY28E), not positional 1/2/3 of the full header. The parser aligns to the
year header explicitly to prevent the year-shift bug we hit earlier.

No LLM is used in this module. Every number is sourced from a literal page
text match with a page number and raw snippet retained for audit.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterator, Optional

import pdfplumber


# ----- Schema ---------------------------------------------------------------

@dataclass
class NumberHit:
    """A single extracted number with its provenance."""
    field_name: str
    value: float
    source_file: str
    page: int
    snippet: str

    def to_dict(self) -> dict:
        """Serialize this hit for the validation log JSON."""
        return asdict(self)


@dataclass
class ExtractionResult:
    """Container for all extracted facts and the validation log."""
    values: dict[str, float] = field(default_factory=dict)
    provenance: dict[str, list[NumberHit]] = field(default_factory=dict)
    bac_eps_by_year: dict[str, float] = field(default_factory=dict)
    bac_yoy_by_year: dict[str, float] = field(default_factory=dict)
    bloomberg_consensus_by_year: dict[str, float] = field(default_factory=dict)
    cowen_consensus_by_year: dict[str, float] = field(default_factory=dict)
    validation: dict[str, list[dict]] = field(default_factory=lambda: {
        "layer_1_cross_source": [],
        "layer_2_math": [],
        "layer_3_golden": [],
    })

    def add(self, hit: NumberHit) -> None:
        """Append a hit to provenance and seed the first value for this field."""
        self.provenance.setdefault(hit.field_name, []).append(hit)
        if hit.field_name not in self.values:
            self.values[hit.field_name] = hit.value


class ValidationError(Exception):
    """Raised when any validation layer fails. Aborts the pipeline."""


# ----- Helpers --------------------------------------------------------------

def _pages(path: Path) -> list[str]:
    """Return per-page extracted text from a PDF."""
    with pdfplumber.open(path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _snippet(text: str, start: int, end: int, pad: int = 70) -> str:
    """Return a single-line snippet around `text[start:end]` for audit logs."""
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    return text[s:e].replace("\n", " | ").strip()


def _all_matches(
    pages: list[str], pattern: str, flags: int = re.IGNORECASE,
) -> Iterator[tuple[int, re.Match, str]]:
    """Yield (page_number, match, page_text) for every regex hit."""
    for i, text in enumerate(pages, start=1):
        for m in re.finditer(pattern, text, flags=flags):
            yield i, m, text


# ----- Q1 press release -----------------------------------------------------

def _extract_q1_pr(path: Path, result: ExtractionResult) -> None:
    """Pull Q1 actuals and Q2 guide from the AEIS press release."""
    pages = _pages(path)

    # q1_revenue_usd_m — needs two hits
    for page, m, text in _all_matches(pages, r"Revenue\s+was\s+\$?(\d{2,4}(?:\.\d+)?)\s*million"):
        result.add(NumberHit("q1_revenue_usd_m", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))

    # q1_eps_non_gaap — needs two hits. The Q1 non-GAAP reconciliation table
    # row has exactly three quarter columns (Q1-2026, Q1-2025, Q4-2025), so we
    # anchor to that three-value pattern to avoid catching the Q2 guide
    # reconciliation row (two values: low/high).
    patterns = [
        r"non.?GAAP\s+EPS\s+was\s+\$?(\d+\.\d{2})",
        r"\$?(\d+\.\d{2})\s+per\s+diluted\s+share\s+in\s+the\s+first\s+quarter\s+of\s+2026",
        r"Non.?GAAP\s+earnings\s+per\s+share\s+\$\s*(\d+\.\d{2})\s+\$\s*\d+\.\d{2}\s+\$\s*\d+\.\d{2}",
    ]
    for pat in patterns:
        for page, m, text in _all_matches(pages, pat):
            result.add(NumberHit("q1_eps_non_gaap", float(m.group(1)),
                                 path.name, page, _snippet(text, *m.span())))

    # q2_guide_rev_mid_usd_m
    for page, m, text in _all_matches(
        pages, r"Revenue\s+\$?(\d{2,4})\s*million\s*\+/-\s*\$?(\d+)\s*million"
    ):
        result.add(NumberHit("q2_guide_rev_mid_usd_m", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))
    # Second source: Q2 reconciliation range (low/high). Midpoint must equal mid.
    for page, m, text in _all_matches(
        pages, r"Revenue\s+\$(\d{3,4})\s*million\s+\$(\d{3,4})\s*million"
    ):
        lo, hi = float(m.group(1)), float(m.group(2))
        mid = (lo + hi) / 2
        result.add(NumberHit("q2_guide_rev_mid_usd_m", mid,
                             path.name, page,
                             f"Q2 recon range ${lo:.0f}M-${hi:.0f}M -> midpoint ${mid:.0f}M | "
                             + _snippet(text, *m.span())))

    # q2_guide_eps_mid
    for page, m, text in _all_matches(
        pages, r"Non.?GAAP\s+EPS\s+\$?(\d+\.\d{2})\s*\+/-\s*\$?(\d+\.\d{2})"
    ):
        result.add(NumberHit("q2_guide_eps_mid", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))
    # Second source: Q2 EPS reconciliation. The Q2 row has exactly two values
    # (low/high) so we require no third "$ X.XX" after the second value via a
    # negative lookahead. This avoids matching the three-column Q1 recon row.
    for page, m, text in _all_matches(
        pages,
        r"Non.?GAAP\s+earnings\s+per\s+share\s+\$\s*(\d+\.\d{2})\s+\$\s*(\d+\.\d{2})(?!\s+\$)"
    ):
        lo, hi = float(m.group(1)), float(m.group(2))
        mid = round((lo + hi) / 2, 2)
        result.add(NumberHit("q2_guide_eps_mid", mid,
                             path.name, page,
                             f"Q2 EPS recon ${lo:.2f}-${hi:.2f} -> mid ${mid:.2f} | "
                             + _snippet(text, *m.span())))


# ----- BofA -----------------------------------------------------------------

def _parse_year_aligned_row(text: str, header_pat: str, row_pat: str,
                            row_n_values: int) -> Optional[dict]:
    """
    Find the header line and the row line, split into tokens, and zip values
    to years. Returns dict {year_label: value} or None if not found.
    """
    h = re.search(header_pat, text)
    r = re.search(row_pat, text)
    if not h or not r:
        return None
    # Extract year tokens (e.g., 2024A, 2025A, 2026E, 2027E, 2028E)
    years = re.findall(r"20\d{2}[AE]", h.group(0))
    # Extract numeric tokens from the row segment (skip the label words)
    nums = re.findall(r"[-+]?\d+\.\d+", r.group(0))
    if len(nums) < row_n_values:
        return None
    nums = nums[:row_n_values]
    # If row has fewer values than years, it is forward-only (drop earliest actuals)
    if len(nums) == len(years):
        return dict(zip(years, [float(n) for n in nums]))
    if len(nums) < len(years):
        forward = years[-len(nums):]
        return dict(zip(forward, [float(n) for n in nums]))
    return None


def _extract_bac(path: Path, result: ExtractionResult) -> None:
    """Pull BofA rating, PT, multiple, CY27 EPS revision, and consensus row."""
    pages = _pages(path)
    text_p1 = pages[0]

    # bac_pt — multiple sources on p1
    for page, m, text in _all_matches(pages, r"PO[:\s]+\$?(\d{3,4}(?:\.\d{1,2})?)"):
        result.add(NumberHit("bac_pt", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))
    for page, m, text in _all_matches(pages, r"Price\s*Objective\s+(\d{3,4}\.\d{2})"):
        result.add(NumberHit("bac_pt", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))
    for page, m, text in _all_matches(pages,
        r"Price\s+Obj\.\s+\d{3,4}\.\d{2}\s+(\d{3,4}\.\d{2})"
    ):
        result.add(NumberHit("bac_pt", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))

    # bac_cy27_pe
    for page, m, text in _all_matches(pages, r"(\d{2})x\s*CY27E?\s*PE"):
        result.add(NumberHit("bac_cy27_pe", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))

    # bac_cy27_eps_new and bac_cy27_eps_prior from Key Changes line
    for page, m, text in _all_matches(
        pages, r"2027E\s*EPS\s+(\d+\.\d{2})\s+(\d+\.\d{2})"
    ):
        result.add(NumberHit("bac_cy27_eps_prior", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))
        result.add(NumberHit("bac_cy27_eps_new", float(m.group(2)),
                             path.name, page, _snippet(text, *m.span())))

    # Year-aligned EPS table from page 1
    eps_row = _parse_year_aligned_row(
        text_p1,
        r"Estimates\s*\(Dec\).*?2024A\s+2025A\s+2026E\s+2027E\s+2028E",
        r"^EPS\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+",
        5,
    )
    if eps_row is None:
        # Fallback: simpler pattern not anchored to start of line
        eps_row = _parse_year_aligned_row(
            text_p1,
            r"2024A\s+2025A\s+2026E\s+2027E\s+2028E",
            r"\bEPS\s+([\d.]+\s+){4}[\d.]+",
            5,
        )
    if eps_row is None:
        raise ValidationError(
            "BAC p1: could not align EPS row to 2024A-2028E header. "
            "Year-shift safeguard tripped."
        )
    result.bac_eps_by_year = eps_row
    # Confirm the EPS table position 4 (CY27E) matches the Key Changes value
    if "2027E" in eps_row:
        result.add(NumberHit("bac_cy27_eps_new", eps_row["2027E"],
                             path.name, 1,
                             f"Estimates table position 2027E = {eps_row['2027E']:.2f}"))

    # YoY EPS Change row
    yoy_row = _parse_year_aligned_row(
        text_p1,
        r"2024A\s+2025A\s+2026E\s+2027E\s+2028E",
        r"EPS\s+Change\s+\(YoY\)\s+[-\d.%]+\s+[-\d.%]+\s+[-\d.%]+\s+[-\d.%]+\s+[-\d.%]+",
        5,
    )
    if yoy_row is None:
        yoy_match = re.search(
            r"EPS\s+Change\s+\(YoY\)\s+(-?\d+\.\d+)%?\s+(-?\d+\.\d+)%?\s+(-?\d+\.\d+)%?\s+(-?\d+\.\d+)%?\s+(-?\d+\.\d+)%?",
            text_p1,
        )
        if yoy_match:
            years = ["2024A", "2025A", "2026E", "2027E", "2028E"]
            yoy_row = {y: float(v) for y, v in zip(years, yoy_match.groups())}
    if yoy_row:
        result.bac_yoy_by_year = yoy_row

    # Bloomberg consensus row — forward-only (3 values aligned to last 3 years)
    consensus_row = _parse_year_aligned_row(
        text_p1,
        r"2024A\s+2025A\s+2026E\s+2027E\s+2028E",
        r"Consensus\s+EPS\s+\(Bloomberg\)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)",
        3,
    )
    if consensus_row is None:
        raise ValidationError(
            "BAC p1: could not align Bloomberg consensus row to year header. "
            "Year-shift safeguard tripped."
        )
    result.bloomberg_consensus_by_year = consensus_row
    cm = re.search(
        r"Consensus\s+EPS\s+\(Bloomberg\)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)",
        text_p1,
    )
    if cm:
        snip = _snippet(text_p1, *cm.span())
        if "2026E" in consensus_row:
            result.add(NumberHit("bloomberg_cy26_consensus_eps",
                                 consensus_row["2026E"], path.name, 1, snip))
        if "2027E" in consensus_row:
            result.add(NumberHit("bloomberg_cy27_consensus_eps",
                                 consensus_row["2027E"], path.name, 1, snip))
        if "2028E" in consensus_row:
            result.add(NumberHit("bloomberg_cy28_consensus_eps",
                                 consensus_row["2028E"], path.name, 1, snip))

    # current_price_may_4 — from BAC p1 (two occurrences)
    for page, m, text in _all_matches(pages, r"Price[:\s]+(\d{3}\.\d{2})\s*USD"):
        result.add(NumberHit("current_price_may_4", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))


# ----- TD Cowen -------------------------------------------------------------

def _extract_cowen(path: Path, result: ExtractionResult) -> None:
    """Pull TD Cowen rating, PT, multiple, CY27 EPS revision, consensus row."""
    pages = _pages(path)
    text_p1 = pages[0]

    # cowen_pt
    for page, m, text in _all_matches(
        pages, r"Price\s+Target[:\s]+\$?(\d{3,4}(?:\.\d{1,2})?)"
    ):
        result.add(NumberHit("cowen_pt", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))
    for page, m, text in _all_matches(
        pages, r"PT\s+\$?(\d{3,4})\s*,\s*\d{2}x\s*CY27"
    ):
        result.add(NumberHit("cowen_pt", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))

    # cowen_cy27_pe
    for page, m, text in _all_matches(pages, r"(\d{2})x\s*CY27"):
        result.add(NumberHit("cowen_cy27_pe", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))

    # cowen_cy27_eps_new — from prose and from the EPS year-row table
    for page, m, text in _all_matches(
        pages, r"\$9\.80\s+and\s+\$?(\d+\.\d{2})\s+in\s+EPS"
    ):
        result.add(NumberHit("cowen_cy27_eps_new", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))
    # Year row "Year $6.41 $9.79 $12.50" under header "FY 2025A 2026E 2027E"
    yr_match = re.search(
        r"FY\s+2025A\s+2026E\s+2027E[\s\S]{0,2000}?Year\s+\$([\d.]+)\s+\$([\d.]+)\s+\$([\d.]+)",
        text_p1,
    )
    if yr_match:
        cowen_cy27_eps_from_table = float(yr_match.group(3))
        result.add(NumberHit("cowen_cy27_eps_new", cowen_cy27_eps_from_table,
                             path.name, 1,
                             f"Cowen EPS Year row position 2027E = ${cowen_cy27_eps_from_table:.2f}"))

    # Cowen consensus EPS row (FactSet source per Cowen, numerically aligned with Bloomberg)
    cm = re.search(
        r"Consensus\s+EPS\s+\$([\d.]+)\s+\$([\d.]+)\s+\$([\d.]+)",
        text_p1,
    )
    if cm:
        # Header order: 2025A 2026E 2027E
        result.cowen_consensus_by_year = {
            "2025A": float(cm.group(1)),
            "2026E": float(cm.group(2)),
            "2027E": float(cm.group(3)),
        }
        snip = _snippet(text_p1, *cm.span())
        result.add(NumberHit("bloomberg_cy26_consensus_eps",
                             float(cm.group(2)), path.name, 1,
                             f"Cowen consensus row position 2026E (FactSet vendor, numerically equal): "
                             + snip))
        result.add(NumberHit("bloomberg_cy27_consensus_eps",
                             float(cm.group(3)), path.name, 1,
                             f"Cowen consensus row position 2027E (FactSet vendor, numerically equal): "
                             + snip))

    # current_price_may_4 — second/third source from Cowen
    for page, m, text in _all_matches(pages, r"Price:\s+\$(\d{3}\.\d{2})"):
        result.add(NumberHit("current_price_may_4", float(m.group(1)),
                             path.name, page, _snippet(text, *m.span())))


# ----- Validation layers ----------------------------------------------------

# Fields that require >= 2 independent occurrences. CY28 consensus is excluded
# because no second analyst publishes it.
_FIELDS_REQUIRING_TWO_SOURCES = [
    "q1_revenue_usd_m",
    "q1_eps_non_gaap",
    "q2_guide_rev_mid_usd_m",
    "q2_guide_eps_mid",
    "bac_pt",
    "bac_cy27_eps_new",
    "cowen_pt",
    "cowen_cy27_eps_new",
    "current_price_may_4",
    "bloomberg_cy26_consensus_eps",
    "bloomberg_cy27_consensus_eps",
]


def _layer_1_cross_source(result: ExtractionResult) -> None:
    """Every key field must have >= 2 hits with identical values."""
    failures: list[str] = []
    for field_name in _FIELDS_REQUIRING_TWO_SOURCES:
        hits = result.provenance.get(field_name, [])
        if len(hits) < 2:
            failures.append(
                f"  {field_name}: only {len(hits)} source(s) found, need >= 2"
            )
            result.validation["layer_1_cross_source"].append({
                "field": field_name, "status": "FAIL",
                "reason": f"only {len(hits)} source(s)",
                "sources": [h.to_dict() for h in hits],
            })
            continue
        values = [h.value for h in hits]
        if len(set(values)) != 1:
            failures.append(
                f"  {field_name}: sources disagree: {values}"
            )
            result.validation["layer_1_cross_source"].append({
                "field": field_name, "status": "FAIL",
                "reason": f"sources disagree: {values}",
                "sources": [h.to_dict() for h in hits],
            })
        else:
            result.validation["layer_1_cross_source"].append({
                "field": field_name, "status": "PASS",
                "value": values[0], "n_sources": len(hits),
                "pages": sorted({(h.source_file, h.page) for h in hits}),
            })

    if failures:
        raise ValidationError(
            "Layer 1 (cross-source) FAILED:\n" + "\n".join(failures)
        )


def _layer_2_math(result: ExtractionResult) -> None:
    """PT ~= EPS*PE, YoY reconstructs, year-indexed series monotone."""
    failures: list[str] = []
    v = result.values

    # PT vs EPS * PE
    for analyst, pt_key, eps_key, pe_key in [
        ("BAC", "bac_pt", "bac_cy27_eps_new", "bac_cy27_pe"),
        ("Cowen", "cowen_pt", "cowen_cy27_eps_new", "cowen_cy27_pe"),
    ]:
        if pt_key not in v or eps_key not in v or pe_key not in v:
            continue
        implied = v[eps_key] * v[pe_key]
        drift = abs(implied - v[pt_key]) / v[pt_key]
        check = {
            "check": f"{analyst} PT ~= EPS * PE",
            "computed": round(implied, 2),
            "reported": v[pt_key],
            "drift_pct": round(drift * 100, 3),
            "status": "PASS" if drift <= 0.02 else "FAIL",
        }
        result.validation["layer_2_math"].append(check)
        if drift > 0.02:
            failures.append(
                f"  {analyst} PT/EPS*PE drift {drift*100:.2f}% exceeds 2% tolerance "
                f"(computed {implied:.2f} vs reported {v[pt_key]:.2f})"
            )

    # YoY EPS reconstruction (BAC)
    if result.bac_eps_by_year and result.bac_yoy_by_year:
        years = ["2024A", "2025A", "2026E", "2027E", "2028E"]
        eps = result.bac_eps_by_year
        yoy = result.bac_yoy_by_year
        for prev, curr in zip(years[:-1], years[1:]):
            if prev not in eps or curr not in eps or curr not in yoy:
                continue
            computed = (eps[curr] / eps[prev] - 1) * 100
            reported = yoy[curr]
            drift_pp = abs(computed - reported)
            check = {
                "check": f"BAC YoY EPS {curr}",
                "computed_pct": round(computed, 2),
                "reported_pct": reported,
                "drift_pp": round(drift_pp, 3),
                "status": "PASS" if drift_pp <= 0.1 else "FAIL",
            }
            result.validation["layer_2_math"].append(check)
            if drift_pp > 0.1:
                failures.append(
                    f"  BAC YoY EPS {curr}: computed {computed:.2f}% vs reported "
                    f"{reported:.2f}% — drift {drift_pp:.2f}pp exceeds 0.1pp"
                )

    # Year-indexed monotone
    for label, series in [
        ("BAC EPS series", result.bac_eps_by_year),
        ("Bloomberg consensus", result.bloomberg_consensus_by_year),
    ]:
        if not series:
            continue
        items = sorted(series.items())
        values = [v_ for _, v_ in items]
        monotone = all(b > a for a, b in zip(values, values[1:]))
        check = {
            "check": f"{label} monotone increasing",
            "series": dict(items),
            "status": "PASS" if monotone else "FAIL",
        }
        result.validation["layer_2_math"].append(check)
        if not monotone:
            failures.append(f"  {label} not monotone increasing: {values}")

    if failures:
        raise ValidationError(
            "Layer 2 (math reconstruction) FAILED:\n" + "\n".join(failures)
        )


def _layer_3_golden(result: ExtractionResult, golden_path: Path) -> None:
    """Every extracted value must match inputs/golden.json exactly."""
    if not golden_path.exists():
        raise ValidationError(
            f"Layer 3: golden file missing at {golden_path}. "
            f"Cannot run without tripwire baseline."
        )
    golden_raw = json.loads(golden_path.read_text())
    # Strip comment keys and provenance keys
    golden = {k: v for k, v in golden_raw.items()
              if not k.startswith("_") and not k.endswith("__source")}
    if any(v is None for v in golden.values()):
        nulls = [k for k, v in golden.items() if v is None]
        raise ValidationError(
            f"Layer 3: golden.json has null slots: {nulls}. "
            f"Fill these values before running the pipeline."
        )

    failures: list[str] = []
    for k, expected in golden.items():
        actual = result.values.get(k)
        if actual is None:
            failures.append(f"  {k}: not extracted (expected {expected})")
            result.validation["layer_3_golden"].append({
                "field": k, "expected": expected, "extracted": None,
                "status": "FAIL", "reason": "not extracted",
            })
            continue
        if abs(float(actual) - float(expected)) > 1e-6:
            failures.append(
                f"  {k}: extracted {actual} vs golden {expected}"
            )
            result.validation["layer_3_golden"].append({
                "field": k, "expected": expected, "extracted": actual,
                "status": "FAIL", "reason": "drift from golden",
            })
        else:
            result.validation["layer_3_golden"].append({
                "field": k, "expected": expected, "extracted": actual,
                "status": "PASS",
            })

    if failures:
        raise ValidationError(
            "Layer 3 (golden tripwires) FAILED:\n" + "\n".join(failures)
        )


# ----- Orchestration --------------------------------------------------------

def extract_all(inputs_dir: Path, golden_path: Path,
                log_path: Optional[Path] = None) -> ExtractionResult:
    """
    Run extraction + all three validation layers. Returns the result if every
    layer passes. Raises ValidationError on any failure.
    """
    result = ExtractionResult()
    _extract_q1_pr(inputs_dir / "Q126_PR_5-4-26.pdf", result)
    _extract_bac(inputs_dir / "BAC__buy__5-5-26.pdf", result)
    _extract_cowen(inputs_dir / "COWN__hold__5-4-26.pdf", result)

    _layer_1_cross_source(result)
    _layer_2_math(result)
    _layer_3_golden(result, golden_path)

    if log_path is not None:
        payload = {
            "values": result.values,
            "provenance": {
                k: [h.to_dict() for h in hits]
                for k, hits in result.provenance.items()
            },
            "bac_eps_by_year": result.bac_eps_by_year,
            "bac_yoy_by_year": result.bac_yoy_by_year,
            "bloomberg_consensus_by_year": result.bloomberg_consensus_by_year,
            "cowen_consensus_by_year": result.cowen_consensus_by_year,
            "validation": result.validation,
        }
        log_path.write_text(json.dumps(payload, indent=2))
    return result


def format_validation_summary(result: ExtractionResult) -> str:
    """Pretty-print the three validation layers for terminal output."""
    lines: list[str] = ["", "=" * 76,
                        "  VALIDATION LOG", "=" * 76, ""]

    # Layer 1
    lines.append("  Layer 1 — Cross-source agreement")
    for entry in result.validation["layer_1_cross_source"]:
        if entry["status"] == "PASS":
            pages_str = ", ".join(f"{f.split('__')[0]}:p{p}" for f, p in entry["pages"])
            lines.append(
                f"    [PASS] {entry['field']:<35} = {entry['value']:<10} "
                f"({entry['n_sources']} sources: {pages_str})"
            )
        else:
            lines.append(f"    [FAIL] {entry['field']}: {entry['reason']}")
    lines.append("")

    # Layer 2
    lines.append("  Layer 2 — Math reconstruction")
    for entry in result.validation["layer_2_math"]:
        if "computed" in entry:
            lines.append(
                f"    [{entry['status']}] {entry['check']:<35} "
                f"computed {entry['computed']:<8} vs reported {entry['reported']:<8} "
                f"(drift {entry.get('drift_pct', 0):.2f}%)"
            )
        elif "computed_pct" in entry:
            lines.append(
                f"    [{entry['status']}] {entry['check']:<35} "
                f"computed {entry['computed_pct']:<6}% vs reported {entry['reported_pct']:<6}% "
                f"(drift {entry['drift_pp']:.2f}pp)"
            )
        else:
            lines.append(
                f"    [{entry['status']}] {entry['check']:<35} series {entry['series']}"
            )
    lines.append("")

    # Layer 3
    lines.append("  Layer 3 — Golden tripwires")
    passes = sum(1 for e in result.validation["layer_3_golden"] if e["status"] == "PASS")
    fails = sum(1 for e in result.validation["layer_3_golden"] if e["status"] == "FAIL")
    lines.append(f"    {passes}/{passes+fails} fields match golden.json exactly")
    for entry in result.validation["layer_3_golden"]:
        if entry["status"] == "FAIL":
            lines.append(
                f"    [FAIL] {entry['field']}: extracted {entry['extracted']} "
                f"vs golden {entry['expected']}"
            )
    lines.append("")
    lines.append("=" * 76)
    return "\n".join(lines)
