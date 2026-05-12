"""
Bear / base / bull scenarios for AEIS, anchored to CY27 non-GAAP EPS x P/E.

All assumptions are named constants at the top of the file. Edit here, re-run
the pipeline, and the Excel + memo artifacts pick up the change. No magic
numbers downstream.

The May 1 spreadsheet used EPS=$10.30 with multiples 25/35/45. Q1 beat and
two analysts raised CY27 EPS substantially. The new scenarios reflect:
  - bear: peer-multiple compression at Bloomberg CY27 consensus
  - base: blended analyst EPS at a moderate premium to peers
  - bull: high-EPS at BofA's bull multiple
"""
from __future__ import annotations

from dataclasses import dataclass

# ----- Scenario constants ---------------------------------------------------

# Bear: market reverts to peer (AMAT/LRCX) multiple, EPS at Bloomberg CY27
# consensus (anchored to BAC consensus row position 2, cross-confirmed at
# Cowen consensus row position 3 — see verification.md).
BEAR_EPS: float = 10.83
BEAR_PE: float = 25.0

# Base: blended BAC ($12.00) and Cowen ($12.50) midpoint at a multiple that
# allows partial premium compression vs current ~32x trading multiple but
# still above peers.
BASE_EPS: float = 12.25
BASE_PE: float = 30.0

# Bull: Cowen's higher EPS at BofA's bull-case multiple.
BULL_EPS: float = 12.50
BULL_PE: float = 36.0

# Probability weights (must sum to 1.0). Override here.
# Reverted to equal weighting to match the PM's original framework.
PROB_BEAR: float = 1 / 3
PROB_BASE: float = 1 / 3
PROB_BULL: float = 1 / 3

# "You are here" anchor: current price implied at Bloomberg CY27 consensus
# times the current trading multiple of ~32x.
CURRENT_TRADING_PE: float = 32.0
CURRENT_TRADING_EPS: float = 10.83  # Bloomberg CY27 consensus

# Sensitivity grid bounds
EPS_GRID_LOW: float = 10.00
EPS_GRID_HIGH: float = 14.00
EPS_GRID_STEP: float = 0.50

PE_GRID_LOW: float = 22.0
PE_GRID_HIGH: float = 40.0
PE_GRID_STEP: float = 2.0


# ----- Computation ----------------------------------------------------------

@dataclass
class Scenario:
    name: str
    eps: float
    pe: float
    probability: float

    @property
    def price(self) -> float:
        """Scenario price = EPS times P/E multiple."""
        return round(self.eps * self.pe, 2)

    def upside_pct(self, current_price: float) -> float:
        """Percent upside (or downside if negative) of this scenario vs spot."""
        return (self.price / current_price - 1) * 100


@dataclass
class ScenarioBundle:
    bear: Scenario
    base: Scenario
    bull: Scenario
    current_price: float

    @property
    def expected_value(self) -> float:
        """Probability weighted price across bear/base/bull."""
        return round(
            self.bear.price * self.bear.probability
            + self.base.price * self.base.probability
            + self.bull.price * self.bull.probability,
            2,
        )

    @property
    def expected_value_upside_pct(self) -> float:
        """Percent change from current price to the probability weighted price."""
        return (self.expected_value / self.current_price - 1) * 100

    @property
    def current_implied_anchor(self) -> float:
        """Implied price at consensus EPS x current trading multiple."""
        return round(CURRENT_TRADING_EPS * CURRENT_TRADING_PE, 2)

    def as_dict(self) -> dict:
        """Serialize the full scenario bundle for downstream consumers."""
        return {
            "scenarios": [
                {"name": s.name, "eps": s.eps, "pe": s.pe,
                 "probability": s.probability, "price": s.price,
                 "upside_pct": round(s.upside_pct(self.current_price), 2)}
                for s in (self.bear, self.base, self.bull)
            ],
            "expected_value": self.expected_value,
            "expected_value_upside_pct": round(self.expected_value_upside_pct, 2),
            "current_price": self.current_price,
            "current_trading_eps": CURRENT_TRADING_EPS,
            "current_trading_pe": CURRENT_TRADING_PE,
            "current_implied_anchor": self.current_implied_anchor,
        }


def build_scenarios(current_price: float) -> ScenarioBundle:
    """Build the bear/base/bull bundle from the constants above."""
    total = PROB_BEAR + PROB_BASE + PROB_BULL
    if abs(total - 1.0) > 1e-6:
        raise ValueError(
            f"Probabilities must sum to 1.0; got {total} "
            f"(bear={PROB_BEAR}, base={PROB_BASE}, bull={PROB_BULL})"
        )
    return ScenarioBundle(
        bear=Scenario("Bear", BEAR_EPS, BEAR_PE, PROB_BEAR),
        base=Scenario("Base", BASE_EPS, BASE_PE, PROB_BASE),
        bull=Scenario("Bull", BULL_EPS, BULL_PE, PROB_BULL),
        current_price=current_price,
    )


def eps_grid() -> list[float]:
    """EPS axis for the sensitivity grid."""
    out: list[float] = []
    v = EPS_GRID_LOW
    while v <= EPS_GRID_HIGH + 1e-9:
        out.append(round(v, 2))
        v += EPS_GRID_STEP
    return out


def pe_grid() -> list[float]:
    """P/E axis for the sensitivity grid."""
    out: list[float] = []
    v = PE_GRID_LOW
    while v <= PE_GRID_HIGH + 1e-9:
        out.append(round(v, 1))
        v += PE_GRID_STEP
    return out


def what_changed_summary(old_eps: float = 10.30,
                         old_bear_pe: float = 25.0,
                         old_base_pe: float = 35.0,
                         old_bull_pe: float = 45.0) -> dict:
    """Diff vs the May 1 spreadsheet baseline."""
    old_bear = round(old_eps * old_bear_pe, 2)
    old_base = round(old_eps * old_base_pe, 2)
    old_bull = round(old_eps * old_bull_pe, 2)
    old_pw = round((old_bear + old_base + old_bull) / 3, 2)

    new_bear = round(BEAR_EPS * BEAR_PE, 2)
    new_base = round(BASE_EPS * BASE_PE, 2)
    new_bull = round(BULL_EPS * BULL_PE, 2)
    new_pw = round(
        new_bear * PROB_BEAR + new_base * PROB_BASE + new_bull * PROB_BULL, 2
    )

    return {
        "eps_old": old_eps,
        "eps_new_bear": BEAR_EPS,
        "eps_new_base": BASE_EPS,
        "eps_new_bull": BULL_EPS,
        "pe_old_bear": old_bear_pe, "pe_new_bear": BEAR_PE,
        "pe_old_base": old_base_pe, "pe_new_base": BASE_PE,
        "pe_old_bull": old_bull_pe, "pe_new_bull": BULL_PE,
        "old_scenarios": {"bear": old_bear, "base": old_base, "bull": old_bull,
                          "prob_weighted_equal": old_pw},
        "new_scenarios": {"bear": new_bear, "base": new_base, "bull": new_bull,
                          "prob_weighted": new_pw},
    }
