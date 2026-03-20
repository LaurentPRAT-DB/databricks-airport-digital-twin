"""
Microsoft Flight Simulator Scenery Data Importer

Parses MSFS airport scenery packages containing gate positions, taxi paths,
runways, and apron areas. Supports both XML source files and compiled BGL
binaries (MSFS 2020 format). Community addons from flightsim.to provide
highly detailed airport definitions that complement OSM data.

Data sources:
- TaxiwayParking: Gate/ramp/dock positions with names and headings
- TaxiwayPoint/TaxiwayPath: Taxi route network
- Runway: Runway geometry with surface types
- Apron: Apron area polygons
"""

from src.formats.msfs.models import (
    MSFSDocument,
    MSFSParkingSpot,
    MSFSTaxiPoint,
    MSFSTaxiPath,
    MSFSRunway,
    MSFSApron,
)
from src.formats.msfs.parser import MSFSParser
from src.formats.msfs.converter import MSFSConverter, merge_msfs_config

__all__ = [
    "MSFSDocument",
    "MSFSParkingSpot",
    "MSFSTaxiPoint",
    "MSFSTaxiPath",
    "MSFSRunway",
    "MSFSApron",
    "MSFSParser",
    "MSFSConverter",
    "merge_msfs_config",
]
