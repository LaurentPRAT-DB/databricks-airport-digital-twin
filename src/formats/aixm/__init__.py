"""
AIXM (Aeronautical Information Exchange Model) Parser

AIXM is the international standard for exchange of aeronautical information
in digital format. Used by FAA SWIM, EUROCONTROL, and aviation authorities
worldwide.

Supports AIXM 5.1.1 schema (current standard).

Resources:
- AIXM website: https://www.aixm.aero/
- FAA SWIM: https://www.faa.gov/air_traffic/technology/swim/
- EUROCONTROL: https://www.eurocontrol.int/
"""

from src.formats.aixm.models import (
    AIXMDocument,
    AIXMRunway,
    AIXMRunwayDirection,
    AIXMTaxiway,
    AIXMApron,
    AIXMNavaid,
    AIXMAirportHeliport,
)
from src.formats.aixm.parser import AIXMParser
from src.formats.aixm.converter import AIXMConverter

__all__ = [
    "AIXMDocument",
    "AIXMRunway",
    "AIXMRunwayDirection",
    "AIXMTaxiway",
    "AIXMApron",
    "AIXMNavaid",
    "AIXMAirportHeliport",
    "AIXMParser",
    "AIXMConverter",
]
