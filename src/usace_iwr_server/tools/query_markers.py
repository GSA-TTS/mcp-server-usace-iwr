"""
query_markers tool
-------------------
Registers the usace_rivermile_query tool on the MCP server.

Filters USACE river mile markers by river name and/or a river-mile value range,
with offset-based pagination.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastmcp import FastMCP
from pydantic import Field

from ..models import LAYER_RIVER_MILE_MARKERS
from ..utils import RiverMileError, _now_utc, build_where, query_where


def register(mcp: FastMCP) -> None:
    """Register the query_markers tool with the MCP server."""

    @mcp.tool(
        name="usace_rivermile_query",
        annotations={
            "title": "Query River Mile Markers by River and Mile Range",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def query_markers(
        river_name: Annotated[Optional[str], Field(
            description=(
                "River name to filter on (case-insensitive substring match against "
                "RIVER_NAME, e.g. 'RED', 'MISSISSIPPI', 'OHIO'). Omit to match all rivers."
            ),
        )] = None,
        mile_min: Annotated[Optional[float], Field(
            description="Minimum river mile value (inclusive). Omit for no lower bound.",
        )] = None,
        mile_max: Annotated[Optional[float], Field(
            description="Maximum river mile value (inclusive). Omit for no upper bound.",
        )] = None,
        limit: Annotated[int, Field(
            description="Maximum markers to return per page. Default 25.",
            ge=1, le=2000,
        )] = 25,
        offset: Annotated[int, Field(
            description="Number of matching markers to skip (for pagination). Default 0.",
            ge=0,
        )] = 0,
    ) -> dict[str, Any]:
        """Query USACE river mile markers by river name and/or mile-value range.

        Use when: "List markers on the RED river", "How many markers on the
        Mississippi between mile 400 and 600?", "Show markers on the Ohio above
        mile 900" (mile_min=900).

        Results are ordered by MILE ascending and paginated. total_count reflects
        all matching markers; use next_offset to fetch the next page.

        Returns:
        {
            "count": int,              # markers on this page
            "total_count": int,        # total markers matching the filter
            "has_more": bool,
            "next_offset": int|null,   # pass as 'offset' to get the next page
            "where": str,              # the WHERE clause applied (for transparency)
            "markers": [ { name, MILE, RIVER_NAME, RIVER_CODE, RIVER_NUMB,
                           LONGITUDE1, LATITUDE1, SOURCE }, ... ],
            "provenance": { source agency, dataset, service URL, layer, CRS, retrieved_utc }
        }

        Error responses:
        - "Error: mile_min cannot be greater than mile_max"
        - "Error: provide at least one filter (river_name, mile_min, or mile_max)"
        - "Error: River Mile request failed: ..."
        """
        try:
            if river_name is None and mile_min is None and mile_max is None:
                return {
                    "error": (
                        "Error: provide at least one filter (river_name, mile_min, "
                        "or mile_max). Use usace_rivermile_find_markers for spatial searches."
                    )
                }
            if mile_min is not None and mile_max is not None and mile_min > mile_max:
                return {"error": "Error: mile_min cannot be greater than mile_max."}

            where = build_where(river_name=river_name, mile_min=mile_min, mile_max=mile_max)
            result = query_where(
                where=where,
                limit=limit,
                offset=offset,
                layer_id=LAYER_RIVER_MILE_MARKERS,
                return_geometry=False,
            )
            result.provenance.retrieved_utc = _now_utc()

            return {
                "count": result.count,
                "total_count": result.total_count,
                "has_more": result.has_more,
                "next_offset": result.next_offset,
                "where": where,
                "markers": result.features,
                "provenance": result.provenance.to_dict(),
            }

        except RiverMileError as exc:
            return {"error": f"Error: River Mile request failed: {exc}"}
