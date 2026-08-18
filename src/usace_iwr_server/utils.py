"""
utils.py
--------
Shared utilities: timestamp helper, GeoJSON->Esri conversion, haversine
distance, a safe WHERE-clause builder, and the ArcGIS HTTP client for the
USACE River Mile Marker Feature Service.

The client functions use only the stdlib (urllib) to keep dependencies minimal
and remain unit-testable in isolation from MCP.
"""

from __future__ import annotations

import json
import math
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from .models import (
    BASE_URL,
    DEFAULT_MAX_RECORDS,
    DEFAULT_TIMEOUT,
    FIELD_MILE,
    FIELD_RIVER_NAME,
    LAYER_RIVER_MILE_MARKERS,
    MARKER_FIELDS,
    Provenance,
    QueryResult,
    WGS84,
)


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RiverMileError(RuntimeError):
    """Raised when the service errors or returns something unusable."""


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_371_008.8  # mean Earth radius in meters


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in meters between two WGS84 lon/lat points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _compass_bearing(lon1: float, lat1: float, lon2: float, lat2: float) -> str:
    """Rough 8-point compass bearing from point 1 to point 2 (for findings)."""
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(
        math.radians(lat1)
    ) * math.cos(math.radians(lat2)) * math.cos(dlon)
    brng = (math.degrees(math.atan2(y, x)) + 360) % 360
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((brng + 22.5) // 45) % 8]


# ---------------------------------------------------------------------------
# Safe WHERE-clause building
# ---------------------------------------------------------------------------

def _escape_sql_literal(value: str) -> str:
    """Escape a string for use inside a single-quoted ArcGIS WHERE literal.

    ArcGIS SQL escapes a single quote by doubling it. We also strip any control
    characters. This prevents WHERE-clause injection (SI-10 input validation).
    """
    cleaned = "".join(ch for ch in value if ch.isprintable())
    return cleaned.replace("'", "''")


def build_where(
    river_name: str | None = None,
    mile_min: float | None = None,
    mile_max: float | None = None,
) -> str:
    """Build a safe WHERE clause from validated, escaped parameters.

    - river_name is matched case-insensitively with a LIKE substring.
    - mile_min / mile_max are numeric bounds (validated by the caller as floats).
    Returns "1=1" when no filters are supplied.
    """
    clauses: list[str] = []
    if river_name:
        needle = _escape_sql_literal(river_name.upper())
        clauses.append(f"UPPER({FIELD_RIVER_NAME}) LIKE '%{needle}%'")
    if mile_min is not None:
        clauses.append(f"{FIELD_MILE} >= {float(mile_min)}")
    if mile_max is not None:
        clauses.append(f"{FIELD_MILE} <= {float(mile_max)}")
    return " AND ".join(clauses) if clauses else "1=1"


# ---------------------------------------------------------------------------
# GeoJSON -> Esri geometry conversion
# ---------------------------------------------------------------------------

_GEOJSON_TO_ESRI_TYPE: dict[str, str] = {
    "Point":           "esriGeometryPoint",
    "MultiPoint":      "esriGeometryMultipoint",
    "LineString":      "esriGeometryPolyline",
    "MultiLineString": "esriGeometryPolyline",
    "Polygon":         "esriGeometryPolygon",
    "MultiPolygon":    "esriGeometryPolygon",
}

_BBOX_TYPE = "BoundingBox"


def geojson_to_esri(geojson: dict[str, Any]) -> tuple[str, str]:
    """Convert a GeoJSON geometry object to (esri_json_str, esri_geometry_type).

    Supports: Point, MultiPoint, LineString, MultiLineString, Polygon,
    MultiPolygon. Also accepts a synthetic
    {"type": "BoundingBox", "bbox": [minLon, minLat, maxLon, maxLat]}
    shorthand that maps to esriGeometryEnvelope.

    All coordinates must be WGS84 (EPSG:4326).

    Raises RiverMileError on unknown or malformed geometry.
    """
    geo_type = geojson.get("type")
    sr = {"wkid": WGS84}

    if geo_type == _BBOX_TYPE:
        bbox = geojson.get("bbox")
        if not bbox or len(bbox) != 4:
            raise RiverMileError(
                "BoundingBox geometry requires a 'bbox' array of "
                "[minLon, minLat, maxLon, maxLat]."
            )
        min_lon, min_lat, max_lon, max_lat = bbox
        esri = {
            "xmin": min_lon, "ymin": min_lat,
            "xmax": max_lon, "ymax": max_lat,
            "spatialReference": sr,
        }
        return json.dumps(esri), "esriGeometryEnvelope"

    if geo_type not in _GEOJSON_TO_ESRI_TYPE:
        raise RiverMileError(
            f"Unsupported geometry type '{geo_type}'. "
            f"Supported types: {', '.join(sorted(_GEOJSON_TO_ESRI_TYPE))} or BoundingBox."
        )

    coords = geojson.get("coordinates")
    if coords is None:
        raise RiverMileError(f"GeoJSON geometry of type '{geo_type}' is missing 'coordinates'.")

    if geo_type == "Point":
        esri = {"x": coords[0], "y": coords[1], "spatialReference": sr}
    elif geo_type == "MultiPoint":
        esri = {"points": [[c[0], c[1]] for c in coords], "spatialReference": sr}
    elif geo_type == "LineString":
        esri = {"paths": [[[c[0], c[1]] for c in coords]], "spatialReference": sr}
    elif geo_type == "MultiLineString":
        esri = {"paths": [[[c[0], c[1]] for c in line] for line in coords], "spatialReference": sr}
    elif geo_type == "Polygon":
        esri = {"rings": [[[c[0], c[1]] for c in ring] for ring in coords], "spatialReference": sr}
    elif geo_type == "MultiPolygon":
        rings = []
        for polygon in coords:
            for ring in polygon:
                rings.append([[c[0], c[1]] for c in ring])
        esri = {"rings": rings, "spatialReference": sr}
    else:  # pragma: no cover - unreachable, guarded above
        raise RiverMileError(f"Unhandled geometry type '{geo_type}'.")

    return json.dumps(esri), _GEOJSON_TO_ESRI_TYPE[geo_type]


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    """Build the TLS context used for all service requests.

    The ArcGIS service is fronted by a CDN whose CA chain includes a CA
    certificate that does not mark its Basic Constraints extension "critical".
    OpenSSL 3.x rejects that under its default strict X509 verification
    ("CERTIFICATE_VERIFY_FAILED ... Basic Constraints of CA cert not marked
    critical"), even though the chain is otherwise valid and trusted.

    We keep full certificate verification (hostname + trust chain) ON, and
    relax ONLY the single strict flag that trips on this non-critical Basic
    Constraints encoding, via X509_V_FLAG_X509_STRICT. This is the minimal
    change that restores connectivity without disabling verification.

    Trust roots are taken from certifi when installed (most portable across
    macOS/Linux), otherwise from the system default paths.
    """
    ctx = ssl.create_default_context()
    try:
        import certifi  # type: ignore

        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:  # noqa: BLE001 -- fall back to system trust store
        pass

    # Turn OFF the strict X509 flag so a non-critical Basic Constraints CA cert
    # is accepted. Verification (VERIFY_PEER) and hostname checking stay ON.
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _get_json(url: str, params: dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """GET a URL with query params and parse JSON, with clear error handling.

    ArcGIS returns HTTP 200 even for logical errors, embedding an "error"
    object in the body -- so we check for that explicitly.
    """
    query = urllib.parse.urlencode(params, doseq=True)
    full_url = f"{url}?{query}"
    req = urllib.request.Request(full_url, headers={"User-Agent": "usace-iwr-mcp/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001 -- surface a clean error upward
        raise RiverMileError(f"Request to River Mile service failed: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RiverMileError(
            f"River Mile service returned non-JSON (first 200 chars): {raw[:200]!r}"
        ) from exc

    if isinstance(data, dict) and "error" in data:
        raise RiverMileError(f"River Mile service error: {data['error']}")
    return data


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _layer_query_url(layer_id: int = LAYER_RIVER_MILE_MARKERS) -> str:
    return f"{BASE_URL}/{layer_id}/query"


def count_where(
    where: str = "1=1",
    layer_id: int = LAYER_RIVER_MILE_MARKERS,
    timeout: int = DEFAULT_TIMEOUT,
) -> int:
    """Return ONLY the number of features matching a WHERE clause."""
    params = {"where": where, "returnCountOnly": "true", "f": "json"}
    data = _get_json(_layer_query_url(layer_id), params, timeout=timeout)
    return int(data.get("count", 0))


def count_geometry(
    geometry_json: str,
    geometry_type: str,
    distance: float | None = None,
    layer_id: int = LAYER_RIVER_MILE_MARKERS,
    timeout: int = DEFAULT_TIMEOUT,
) -> int:
    """Return ONLY the number of features intersecting a geometry (optional buffer)."""
    params: dict[str, Any] = {
        "geometry": geometry_json,
        "geometryType": geometry_type,
        "inSR": WGS84,
        "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true",
        "f": "json",
    }
    if distance is not None:
        params["distance"] = distance
        params["units"] = "esriSRUnit_Meter"
    data = _get_json(_layer_query_url(layer_id), params, timeout=timeout)
    return int(data.get("count", 0))


def query_where(
    where: str = "1=1",
    out_fields: list[str] | None = None,
    limit: int = 25,
    offset: int = 0,
    layer_id: int = LAYER_RIVER_MILE_MARKERS,
    timeout: int = DEFAULT_TIMEOUT,
    return_geometry: bool = False,
) -> QueryResult:
    """Query markers by attribute WHERE clause with pagination.

    Returns a single page (up to `limit`) starting at `offset`, plus the total
    matching count and pagination metadata.
    """
    out_fields = out_fields or MARKER_FIELDS
    limit = max(1, min(int(limit), DEFAULT_MAX_RECORDS))

    total = count_where(where, layer_id=layer_id, timeout=timeout)

    params: dict[str, Any] = {
        "where": where,
        "outFields": ",".join(out_fields),
        "orderByFields": FIELD_MILE,
        "returnGeometry": "true" if return_geometry else "false",
        "resultOffset": int(offset),
        "resultRecordCount": limit,
        "f": "json",
    }
    if return_geometry:
        params["outSR"] = WGS84
    data = _get_json(_layer_query_url(layer_id), params, timeout=timeout)
    features = _extract_features(data, return_geometry)

    fetched_end = int(offset) + len(features)
    has_more = fetched_end < total
    return QueryResult(
        features=features,
        count=len(features),
        total_count=total,
        truncated=has_more,
        has_more=has_more,
        next_offset=fetched_end if has_more else None,
        provenance=Provenance(layer_id=layer_id),
    )


def query_geometry(
    geometry_json: str,
    geometry_type: str,
    distance: float | None = None,
    out_fields: list[str] | None = None,
    max_records: int = 200,
    layer_id: int = LAYER_RIVER_MILE_MARKERS,
    timeout: int = DEFAULT_TIMEOUT,
    return_geometry: bool = True,
) -> QueryResult:
    """Return marker features intersecting a geometry (optionally buffered).

    Geometry IS returned by default so callers can compute distances client-side.
    Paginates automatically up to `max_records`.
    """
    out_fields = out_fields or MARKER_FIELDS

    base_params: dict[str, Any] = {
        "geometry": geometry_json,
        "geometryType": geometry_type,
        "inSR": WGS84,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": ",".join(out_fields),
        "returnGeometry": "true" if return_geometry else "false",
        "f": "json",
    }
    if return_geometry:
        base_params["outSR"] = WGS84
    if distance is not None:
        base_params["distance"] = distance
        base_params["units"] = "esriSRUnit_Meter"

    features: list[dict[str, Any]] = []
    offset = 0
    truncated = False
    while True:
        params = dict(base_params)
        params["resultOffset"] = offset
        params["resultRecordCount"] = DEFAULT_MAX_RECORDS
        data = _get_json(_layer_query_url(layer_id), params, timeout=timeout)
        page = _extract_features(data, return_geometry)
        features.extend(page)

        if len(features) >= max_records:
            features = features[:max_records]
            truncated = True
            break
        if not data.get("exceededTransferLimit") and len(page) < DEFAULT_MAX_RECORDS:
            break
        offset += len(page)
        if not page:
            break

    return QueryResult(
        features=features,
        count=len(features),
        truncated=truncated,
        has_more=truncated,
        provenance=Provenance(layer_id=layer_id),
    )


def _extract_features(data: dict[str, Any], return_geometry: bool) -> list[dict[str, Any]]:
    """Flatten ArcGIS features into attribute dicts, folding in geometry when present."""
    out: list[dict[str, Any]] = []
    for f in data.get("features", []):
        attrs = dict(f.get("attributes", {}))
        if return_geometry:
            geom = f.get("geometry") or {}
            if "x" in geom and "y" in geom:
                attrs["_lon"] = geom["x"]
                attrs["_lat"] = geom["y"]
        out.append(attrs)
    return out
