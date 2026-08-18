"""
nearest_marker tool
--------------------
Registers the usace_rivermile_nearest tool on the MCP server.

Returns the single closest river mile marker to a coordinate -- the classic
"what river mile am I at?" use case.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastmcp import FastMCP
from pydantic import Field

from ..models import FIELD_LAT, FIELD_LON, FIELD_MILE, FIELD_RIVER_NAME, LAYER_RIVER_MILE_MARKERS, WGS84
from ..utils import (
    RiverMileError,
    _compass_bearing,
    _now_utc,
    geojson_to_esri,
    haversine_m,
    query_geometry,
)

DEFAULT_MAX_RADIUS_M = 50_000.0


def register(mcp: FastMCP) -> None:
    """Register the nearest_marker tool with the MCP server."""

    @mcp.tool(
        name="usace_rivermile_nearest",
        annotations={
            "title": "Nearest River Mile Marker to a Location",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def nearest_marker(
        lat: Annotated[float, Field(
            description="Latitude in decimal degrees (WGS84).",
            ge=-90, le=90,
        )],
        lon: Annotated[float, Field(
            description="Longitude in decimal degrees (WGS84).",
            ge=-180, le=180,
        )],
        max_radius_meters: Annotated[float, Field(
            description=(
                "Maximum search radius in meters. If no marker is found within this "
                "radius, the tool reports none found. Default 50000 (50 km)."
            ),
            gt=0, le=500_000,
        )] = DEFAULT_MAX_RADIUS_M,
    ) -> dict[str, Any]:
        """Return the single closest river mile marker to a WGS84 coordinate.

        Answers "what river mile am I at?" / "nearest marker to this point".
        Searches within max_radius_meters and returns the nearest marker with its
        great-circle distance, plus a plain-language finding.

        Returns:
        {
            "finding": str,            # e.g. "Nearest marker: RED River, Mile 111, ~180 m NE"
            "found": bool,
            "nearest": { name, MILE, RIVER_NAME, RIVER_CODE, RIVER_NUMB,
                         LONGITUDE1, LATITUDE1, SOURCE, distance_m, bearing } | null,
            "candidates_searched": int,
            "query": { "lat": float, "lon": float, "max_radius_meters": float, "crs_epsg": int },
            "provenance": { source agency, dataset, service URL, layer, CRS, retrieved_utc }
        }

        Error responses:
        - "Error: River Mile request failed: ..."
        """
        try:
            geojson = {"type": "Point", "coordinates": [lon, lat]}
            geometry_json, esri_type = geojson_to_esri(geojson)
            result = query_geometry(
                geometry_json=geometry_json,
                geometry_type=esri_type,
                distance=float(max_radius_meters),
                layer_id=LAYER_RIVER_MILE_MARKERS,
                return_geometry=True,
            )

            best: Optional[dict[str, Any]] = None
            best_dist = float("inf")
            for attrs in result.features:
                mlon = attrs.get("_lon", attrs.get(FIELD_LON))
                mlat = attrs.get("_lat", attrs.get(FIELD_LAT))
                if mlon is None or mlat is None:
                    continue
                d = haversine_m(lon, lat, mlon, mlat)
                if d < best_dist:
                    best_dist = d
                    best = attrs

            prov = result.provenance
            prov.retrieved_utc = _now_utc()
            query_meta = {
                "lat": lat, "lon": lon,
                "max_radius_meters": float(max_radius_meters),
                "crs_epsg": WGS84,
            }

            if best is None:
                return {
                    "finding": (
                        f"No river mile marker found within "
                        f"{int(max_radius_meters)} m of ({lat}, {lon})."
                    ),
                    "found": False,
                    "nearest": None,
                    "candidates_searched": len(result.features),
                    "query": query_meta,
                    "provenance": prov.to_dict(),
                }

            record = {k: v for k, v in best.items() if not k.startswith("_")}
            mlon = best.get("_lon", best.get(FIELD_LON))
            mlat = best.get("_lat", best.get(FIELD_LAT))
            record["distance_m"] = round(best_dist, 1)
            record["bearing"] = _compass_bearing(lon, lat, mlon, mlat)

            river = record.get(FIELD_RIVER_NAME, "unknown river")
            mile = record.get(FIELD_MILE, "?")
            finding = (
                f"Nearest marker: {river} River, Mile {mile}, "
                f"~{record['distance_m']:.0f} m {record['bearing']}."
            )

            return {
                "finding": finding,
                "found": True,
                "nearest": record,
                "candidates_searched": len(result.features),
                "query": query_meta,
                "provenance": prov.to_dict(),
            }

        except RiverMileError as exc:
            return {"error": f"Error: River Mile request failed: {exc}"}
