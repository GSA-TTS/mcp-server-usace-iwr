"""
find_markers tool
-----------------
Registers the usace_rivermile_find_markers tool on the MCP server.

Finds USACE river mile markers near a location (lat/lon + radius) or within an
arbitrary GeoJSON geometry. For point queries, results include a computed
distance in meters and are sorted nearest-first.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

from fastmcp import FastMCP
from pydantic import Field

from ..models import FIELD_LAT, FIELD_LON, LAYER_RIVER_MILE_MARKERS, WGS84
from ..utils import (
    RiverMileError,
    _compass_bearing,
    _now_utc,
    geojson_to_esri,
    haversine_m,
    query_geometry,
)

DEFAULT_RADIUS_M = 5000.0


def register(mcp: FastMCP) -> None:
    """Register the find_markers tool with the MCP server."""

    @mcp.tool(
        name="usace_rivermile_find_markers",
        annotations={
            "title": "Find River Mile Markers Near a Location",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def find_markers(
        lat: Annotated[Optional[float], Field(
            description=(
                "Latitude in decimal degrees (WGS84). Use with 'lon' for a proximity "
                "search. Omit when supplying 'geometry'."
            ),
            ge=-90, le=90,
        )] = None,
        lon: Annotated[Optional[float], Field(
            description=(
                "Longitude in decimal degrees (WGS84). Use with 'lat' for a proximity "
                "search. Omit when supplying 'geometry'."
            ),
            ge=-180, le=180,
        )] = None,
        radius_meters: Annotated[float, Field(
            description=(
                "Search radius in meters around the lat/lon point. Ignored when "
                "'geometry' is supplied. Default 5000 (5 km)."
            ),
            gt=0, le=500_000,
        )] = DEFAULT_RADIUS_M,
        geometry: Annotated[Optional[str], Field(
            description=(
                "GeoJSON geometry object as a JSON string. Supported types: "
                "Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon. "
                "Also accepts BoundingBox shorthand: "
                '{"type": "BoundingBox", "bbox": [minLon, minLat, maxLon, maxLat]}. '
                "All coordinates must be WGS84 decimal degrees. "
                "Supply either this OR lat+lon, not both."
            ),
        )] = None,
        limit: Annotated[int, Field(
            description="Maximum number of markers to return. Default 25.",
            ge=1, le=2000,
        )] = 25,
    ) -> dict[str, Any]:
        """Find USACE river mile markers near a point or within a geometry.

        Accepts EITHER a lat/lon pair (+ radius_meters) OR a GeoJSON geometry string.

        Use lat+lon when: "What river mile markers are near 31.45, -92.71?",
            "Markers within 2 km of this boat ramp?"
        Use geometry when: "Which markers fall inside this county polygon / bbox?",
            "Markers along this river-reach corridor?"

        For point (lat/lon) queries, each returned marker includes 'distance_m'
        (great-circle meters from the query point) and results are sorted
        nearest-first. Geometry queries return markers intersecting the geometry.

        Returns:
        {
            "count": int,              # markers returned (after limit)
            "truncated": bool,         # true if more markers matched than returned
            "markers": [ { name, MILE, RIVER_NAME, RIVER_CODE, RIVER_NUMB,
                           LONGITUDE1, LATITUDE1, SOURCE, distance_m? }, ... ],
            "query": { "type": str, "radius_meters": float|null, "crs_epsg": int },
            "provenance": { source agency, dataset, service URL, layer, CRS, retrieved_utc }
        }

        Error responses:
        - "Error: supply either lat+lon or geometry, not both (or neither)"
        - "Error: 'geometry' is not valid JSON: ..."
        - "Error: unsupported geometry type ..."
        - "Error: River Mile request failed: ..."
        """
        try:
            point: Optional[tuple[float, float]] = None
            distance: Optional[float] = None

            if lat is not None and lon is not None and geometry is None:
                geojson = {"type": "Point", "coordinates": [lon, lat]}
                point = (lon, lat)
                distance = float(radius_meters)
            elif geometry is not None and lat is None and lon is None:
                try:
                    geojson = json.loads(geometry)
                except json.JSONDecodeError as exc:
                    return {"error": f"Error: 'geometry' is not valid JSON: {exc}"}
            else:
                return {"error": "Error: supply either lat+lon or geometry, not both (or neither)."}

            geo_type = geojson.get("type", "Unknown")
            geometry_json, esri_type = geojson_to_esri(geojson)
            result = query_geometry(
                geometry_json=geometry_json,
                geometry_type=esri_type,
                distance=distance,
                layer_id=LAYER_RIVER_MILE_MARKERS,
                return_geometry=True,
            )

            markers = _finalize_markers(result.features, point)
            truncated = result.truncated or len(markers) > limit
            markers = markers[:limit]

            out: dict[str, Any] = {
                "count": len(markers),
                "truncated": truncated,
                "markers": markers,
                "query": {
                    "type": geo_type,
                    "radius_meters": distance,
                    "crs_epsg": WGS84,
                },
            }
            prov = result.provenance
            prov.retrieved_utc = _now_utc()
            out["provenance"] = prov.to_dict()
            return out

        except RiverMileError as exc:
            return {"error": f"Error: River Mile request failed: {exc}"}


def _finalize_markers(
    features: list[dict[str, Any]],
    point: Optional[tuple[float, float]],
) -> list[dict[str, Any]]:
    """Strip internal geometry keys, add distance/bearing for point queries, sort."""
    out: list[dict[str, Any]] = []
    for attrs in features:
        mlon = attrs.pop("_lon", attrs.get(FIELD_LON))
        mlat = attrs.pop("_lat", attrs.get(FIELD_LAT))
        record = dict(attrs)
        if point is not None and mlon is not None and mlat is not None:
            qlon, qlat = point
            record["distance_m"] = round(haversine_m(qlon, qlat, mlon, mlat), 1)
            record["bearing"] = _compass_bearing(qlon, qlat, mlon, mlat)
        out.append(record)
    if point is not None:
        out.sort(key=lambda r: r.get("distance_m", float("inf")))
    return out
