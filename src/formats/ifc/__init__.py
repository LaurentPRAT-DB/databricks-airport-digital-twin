"""
IFC (Industry Foundation Classes) Parser

IFC is the ISO standard (ISO 16739) for BIM (Building Information Modeling)
data exchange. Used by architects and construction professionals to share
building design data.

Supports IFC4 schema (current ISO standard).

This module requires the `ifcopenshell` library which provides comprehensive
IFC parsing capabilities. If not available, a fallback stub parser is used.

Resources:
- IFC specification: https://www.buildingsmart.org/standards/bsi-standards/industry-foundation-classes/
- ifcopenshell: https://ifcopenshell.org/
- Sample files: https://github.com/buildingSMART/Sample-Test-Files
"""

from src.formats.ifc.models import (
    IFCDocument,
    IFCBuilding,
    IFCBuildingStorey,
    IFCSpace,
    IFCElement,
    IFCMaterial,
    IFCGeometry,
)
from src.formats.ifc.parser import IFCParser, IFCOPENSHELL_AVAILABLE
from src.formats.ifc.converter import IFCConverter

__all__ = [
    "IFCDocument",
    "IFCBuilding",
    "IFCBuildingStorey",
    "IFCSpace",
    "IFCElement",
    "IFCMaterial",
    "IFCGeometry",
    "IFCParser",
    "IFCConverter",
    "IFCOPENSHELL_AVAILABLE",
]
