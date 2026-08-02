"""Solvency II non-life underwriting risk — Aurelia Assicurazioni S.p.A."""
from .premium_reserve import (
    PremiumReserveRisk,
    geographic_diversification_factor,
    herfindahl_index,
)

__all__ = ["PremiumReserveRisk", "geographic_diversification_factor",
           "herfindahl_index"]
__version__ = "1.0.0"
