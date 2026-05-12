"""
Single end-to-end entry point: extract -> validate -> qualitative -> scenarios
-> Excel -> memo (docx).

Aborts on any extract.py validation failure. Aborts on missing
outputs/qualitative.json with a clear message (the file ships hand-authored).

Usage:
    python run.py

All artifacts land in outputs/.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src import extract, excel_writer, memo, qualitative, scenarios


def main() -> int:
    """Run the full pipeline. Returns a process exit code."""
    inputs = ROOT / "inputs"
    outputs = ROOT / "outputs"
    outputs.mkdir(exist_ok=True)

    extraction_log = outputs / "extraction_log.json"
    qual_cache = outputs / "qualitative.json"
    excel_out = outputs / "AEIS_Valuation_updated.xlsx"
    memo_out = outputs / "memo.docx"

    print("\n[1/4] Extracting and validating PDFs...")
    try:
        result = extract.extract_all(
            inputs_dir=inputs,
            golden_path=inputs / "golden.json",
            log_path=extraction_log,
        )
    except extract.ValidationError as e:
        print("\nPIPELINE ABORTED — extraction validation failed:")
        print(str(e))
        return 1
    print(extract.format_validation_summary(result))

    current_price = result.values["current_price_may_4"]

    print("[2/4] Loading qualitative content...")
    qual = qualitative.run(inputs, qual_cache)
    if qual is None:
        print(f"      WARNING: {qual_cache} not found.")
        print(f"      The memo prose is hand-authored and does not depend "
              f"on this file, but it is part of the audit trail. Recreate "
              f"if missing.\n")
        qual = {}
    else:
        review_total = sum(
            len(idxs) for qr in qual.values()
            for idxs in qr.review_flags.values()
        )
        print(f"      Loaded both analysts. {review_total} bullet(s) flagged "
              f"[REVIEW] by AEIS whitelist soft check.\n")

    print("[3/4] Building scenarios and writing xlsx...")
    bundle = scenarios.build_scenarios(current_price=current_price)
    print(f"      Bear ${bundle.bear.price:.0f} | Base ${bundle.base.price:.0f} | "
          f"Bull ${bundle.bull.price:.0f} | PW ${bundle.expected_value:.0f} "
          f"({bundle.expected_value_upside_pct:+.1f}% vs ${current_price:.2f})")
    excel_writer.write(
        template_path=inputs / "AEIS_Valuation.xlsx",
        output_path=excel_out,
        bundle=bundle,
    )
    print(f"      -> {excel_out}\n")

    print("[4/4] Writing memo.docx...")
    try:
        report = memo.write_memo(memo_out)
    except ValueError as e:
        print(f"\nPIPELINE ABORTED — memo build failed: {e}")
        return 1
    print(f"      -> {report['path']} ({report['word_count']} words, "
          f"scan: {'clean' if not report['banned_findings'] else report['banned_findings']})")
    print(f"      -> {report['pdf_path']} ({report['pdf_pages']} page(s), "
          f"line_spacing={report['line_spacing']}, "
          f"margin={report['margin_inches']}\")")

    print("\nPipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
