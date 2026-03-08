"""
OpenStreetMap Airport Data Importer

Fetches airport gates, terminals, and POIs from OpenStreetMap via Overpass API.
OSM provides community-contributed data for airport infrastructure that complements
official AIXM data.

Data sources:
- aeroway=gate: Gate positions with ref numbers
- aeroway=terminal / building=terminal: Terminal building outlines
- aeroway=taxiway: Taxiway centerlines (if not using AIXM)
"""

from src.formats.osm.models import OSMDocument, OSMNode, OSMWay
from src.formats.osm.parser import OSMParser
from src.formats.osm.converter import OSMConverter, merge_osm_config

__all__ = [
    "OSMDocument",
    "OSMNode",
    "OSMWay",
    "OSMParser",
    "OSMConverter",
    "merge_osm_config",
]
