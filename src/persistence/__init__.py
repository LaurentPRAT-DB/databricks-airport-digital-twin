"""Airport data persistence module.

Provides persistence of airport configuration to Unity Catalog tables.
"""

from src.persistence.airport_repository import AirportRepository, get_airport_repository

__all__ = ["AirportRepository", "get_airport_repository"]
