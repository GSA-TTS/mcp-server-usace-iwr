"""
models.py
---------
Data models and constants for the USACE River Mile Marker client.

These dataclasses carry structured results and provenance information
between the client functions and the MCP tool layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Service constants
# ---------------------------------------------------------------------------

# USACE IWR River Mile Marker hosted Feature Service, layer 0 (point layer).
BASE_URL = (
    "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/"
    "usace_river_mile_markers/FeatureServer"
)
LAYER_RIVER_MILE_MARKERS = 0

# WGS84 lon/lat. This is what GPS coordinates are in, and what we require
# callers to pass. We NEVER silently assume a different CRS.
WGS84 = 4326

# The service caps each response at this many records. Above this you MUST page.
DEFAULT_MAX_RECORDS = 2000

# Default page size for list-style tools (kept small for the agent's context).
DEFAULT_LIMIT = 25

DEFAULT_TIMEOUT = 30  # seconds

# ---------------------------------------------------------------------------
# Field names (confirmed from the live layer schema)
# ---------------------------------------------------------------------------
# Attribute fields present on the layer:
#   name        - marker label (usually the mile number as a string)
#   LONGITUDE1  - marker longitude (WGS84)
#   LATITUDE1   - marker latitude (WGS84)
#   MILE        - river mile value (numeric)
#   RIVER_CODE  - short river code (e.g. "RD")
#   RIVER_NAME  - river name (e.g. "RED")
#   RIVER_NUMB  - internal river number
#   SOURCE      - data source (e.g. "IENC")

FIELD_NAME = "name"
FIELD_LON = "LONGITUDE1"
FIELD_LAT = "LATITUDE1"
FIELD_MILE = "MILE"
FIELD_RIVER_CODE = "RIVER_CODE"
FIELD_RIVER_NAME = "RIVER_NAME"
FIELD_RIVER_NUMB = "RIVER_NUMB"
FIELD_SOURCE = "SOURCE"

# Attributes worth returning for a marker. Explicit > wildcard: keeps payloads
# small and makes the contract stable.
MARKER_FIELDS = [
    FIELD_NAME,
    FIELD_MILE,
    FIELD_RIVER_NAME,
    FIELD_RIVER_CODE,
    FIELD_RIVER_NUMB,
    FIELD_LON,
    FIELD_LAT,
    FIELD_SOURCE,
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Provenance:
    """Where a result came from -- non-negotiable for an authoritative record."""
    source_agency: str = "USACE"
    dataset: str = "River Mile Markers (IWR)"
    service_url: str = BASE_URL
    layer_id: int | None = LAYER_RIVER_MILE_MARKERS
    crs_epsg: int = WGS84
    retrieved_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_agency": self.source_agency,
            "dataset": self.dataset,
            "service_url": self.service_url,
            "layer_id": self.layer_id,
            "crs_epsg": self.crs_epsg,
            "retrieved_utc": self.retrieved_utc,
        }


@dataclass
class QueryResult:
    """A compact, model-friendly answer with provenance attached."""
    features: list[dict[str, Any]] = field(default_factory=list)
    count: int = 0
    total_count: int | None = None   # total matching before pagination, when known
    truncated: bool = False          # True if capped at a limit
    has_more: bool = False
    next_offset: int | None = None
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "total_count": self.total_count,
            "truncated": self.truncated,
            "has_more": self.has_more,
            "next_offset": self.next_offset,
            "features": self.features,
            "provenance": self.provenance.to_dict(),
        }
