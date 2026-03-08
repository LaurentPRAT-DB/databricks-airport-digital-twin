"""
AIDM (IATA Airport Industry Data Model) Parser

AIDM is the IATA standard for airport operational data exchange.
Used for sharing flight information, resource allocation, and
event notifications between airport systems.

Supports AIDM 12.0 specification.

Resources:
- IATA AIDM: https://www.iata.org/en/programs/ops-infra/aidm/
- Data Dictionary: Available to IATA members
"""

from src.formats.aidm.models import (
    AIDMDocument,
    AIDMFlight,
    AIDMFlightLeg,
    AIDMResource,
    AIDMResourceType,
    AIDMEvent,
    AIDMEventType,
    AIDMGate,
    AIDMBaggageClaim,
    AIDMCheckIn,
)
from src.formats.aidm.parser import AIDMParser
from src.formats.aidm.converter import AIDMConverter

__all__ = [
    "AIDMDocument",
    "AIDMFlight",
    "AIDMFlightLeg",
    "AIDMResource",
    "AIDMResourceType",
    "AIDMEvent",
    "AIDMEventType",
    "AIDMGate",
    "AIDMBaggageClaim",
    "AIDMCheckIn",
    "AIDMParser",
    "AIDMConverter",
]
