# Golden value verification — audit trail

**Date verified:** 2026-05-12
**Verifier:** Claude (extraction) + Pranav (eyeball confirmation)
**Source files:**
- `inputs/Q126_PR_5-4-26.pdf` — AEIS Q1 2026 press release
- `inputs/BAC__buy__5-5-26.pdf` — BofA Securities, BUY, 5 May 2026
- `inputs/COWN__hold__5-4-26.pdf` — TD Cowen, HOLD, 4 May 2026

This is the baseline against which `extract.py` Layer 3 runs on every pipeline execution. Any drift from these 15 values aborts the run.

## Rows 1–12

| # | Field | Value | Sources verified |
|---|---|---|---|
| 1 | current_price_may_4 | 387.03 | BAC p1 header `Price: 387.03 USD`; BAC p1 Stock Data block `Price 387.03 USD`; Cowen p1 `Price: $387.03 (05/4/2026)` — triple-confirmed |
| 2 | bac_pt | 430.00 | BAC p1 header `PO: 430.00 USD`; BAC p1 Key Changes `Price Obj. 330.00 430.00`; BAC p1 Stock Data `Price Objective 430.00 USD` |
| 3 | cowen_pt | 350.00 | Cowen p1 `Price Target: $350.00 (Prior $300.00)`; Cowen p1 `Remain Hold (PT $350, 28x CY27)` |
| 4 | bac_cy27_pe | 36.0 | BAC p1 `now on 36x CY27E PE (vs. 33x prior on higher CY27-28 demand visibility)` |
| 5 | cowen_cy27_pe | 28.0 | Cowen p1 `Remain Hold (PT $350, 28x CY27)` |
| 6 | bac_cy27_eps_new | 12.00 | BAC p1 Key Changes `2027E EPS 9.90 12.00` (right column = Current); BAC p1 estimates table position 4 of 5 under header `2024A 2025A 2026E 2027E 2028E`; BAC p3 fiscal table |
| 7 | bac_cy27_eps_prior | 9.90 | BAC p1 Key Changes `2027E EPS 9.90 12.00` (left column = Previous, per header `(US$) Previous Current`) |
| 8 | cowen_cy27_eps_new | 12.50 | Cowen p1 prose `we see ~$9.80 and $12.50 in EPS for CY26/27, respectively`; Cowen p1 EPS table `Year $6.41 $9.79 $12.50` under header `FY 2025A 2026E 2027E` (position 3 = CY27E) |
| 9 | q1_revenue_usd_m | 511.0 | Q1 PR p5 first bullet `Revenue was $511 million`; Q1 PR p5 body `Revenue was $511 million in the first quarter of 2026` |
| 10 | q1_eps_non_gaap | 2.09 | Q1 PR p5 fourth bullet `non-GAAP EPS was $2.09`; Q1 PR p5 body `Non-GAAP net income was $83 million or $2.09 per diluted share` |
| 11 | q2_guide_rev_mid_usd_m | 540.0 | Q1 PR p6 guidance table `Revenue $540 million +/- $20 million` |
| 12 | q2_guide_eps_mid | 2.18 | Q1 PR p6 guidance table `Non-GAAP EPS $2.18 +/- $0.25` |

## Rows 13–15 — Bloomberg consensus year-alignment block

Raw BAC p1 block (verbatim from pdfplumber):

```
Estimates (Dec) (US$) 2024A 2025A 2026E 2027E 2028E
EPS 3.71 6.41 9.36 12.00 14.12 Stock Data
GAAP EPS 1.49 3.86 6.74 8.83 10.68
EPS Change (YoY) -24.0% 72.8% 46.0% 28.2% 17.7% Price 387.03 USD
Consensus EPS (Bloomberg) 8.75 10.83 12.33 Price Objective 430.00 USD
Consensus EPS (Visible Alpha) 6.62 8.55 9.44 Date Established 5-May-2026
```

**Year alignment logic:** Header has 5 year columns (`2024A 2025A 2026E 2027E 2028E`). The EPS, GAAP EPS, EPS Change (YoY), and DPS rows fill all 5 columns. The consensus rows fill **only 3 values** — they are forward-only (Bloomberg and Visible Alpha drop fully-reported actuals once a year closes). Therefore consensus positions 1/2/3 map to CY26E / CY27E / CY28E.

**Cross-validation against Cowen p1:**

```
FY               2025A    2026E    2027E
Year             $6.41    $9.79    $12.50
Consensus EPS    $6.41    $8.75    $10.83
```

Cowen consensus row position 2 (CY26E) = $8.75 → matches BAC consensus position 1 = $8.75 → both confirm CY26E.
Cowen consensus row position 3 (CY27E) = $10.83 → matches BAC consensus position 2 = $10.83 → both confirm CY27E.
BAC consensus position 3 = $12.33 = CY28E (BAC's last header column; Cowen has no CY28 column, so single-source).

| # | Field | Value | Sources verified |
|---|---|---|---|
| 13 | bloomberg_cy26_consensus_eps | 8.75 | BAC consensus row col 1 AND Cowen consensus row col 2 — both aligned to CY26E |
| 14 | bloomberg_cy27_consensus_eps | 10.83 | BAC consensus row col 2 AND Cowen consensus row col 3 — both aligned to CY27E |
| 15 | bloomberg_cy28_consensus_eps | 12.33 | BAC consensus row col 3 (CY28E). Single-source. Passes monotone-increasing check: $10.83 < $12.33. |

**Caveat on Cowen label:** Cowen reports its consensus row source as "FactSet" while BAC reports "Bloomberg." Numerical values match exactly at the overlapping CY26E and CY27E positions ($8.75 and $10.83), so the cross-check is valid regardless of vendor label — for large-cap names FactSet and Bloomberg consensus EPS are typically identical.

## Math reconstruction spot-checks

| Check | Computed | Reported | Drift |
|---|---|---|---|
| BAC PT ≈ EPS × PE | 12.00 × 36 = 432.00 | 430.00 | +0.46% |
| Cowen PT ≈ EPS × PE | 12.50 × 28 = 350.00 | 350.00 | 0.00% |
| BAC YoY 2026E vs 2025A | (9.36 / 6.41) − 1 = 45.96% | 46.0% | <0.05pp |
| BAC YoY 2027E vs 2026E | (12.00 / 9.36) − 1 = 28.21% | 28.2% | <0.05pp |
| BAC YoY 2028E vs 2027E | (14.12 / 12.00) − 1 = 17.67% | 17.7% | <0.05pp |
| BAC EPS series monotone | 3.71 < 6.41 < 9.36 < 12.00 < 14.12 | — | ✓ |
| Bloomberg consensus monotone | 8.75 < 10.83 < 12.33 | — | ✓ |

All checks pass. The 15 values in `inputs/golden.json` are locked.
