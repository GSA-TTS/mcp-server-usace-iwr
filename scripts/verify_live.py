#!/usr/bin/env python3
"""
verify_live.py
--------------
Live smoke-test + answer-verification helper for the USACE IWR River Mile
Marker MCP server.

Run this from a network that can reach services7.arcgis.com (the CI/dev sandbox
used to author the server blocks it with HTTP 403). It exercises every client
path the three tools depend on and prints results you can paste into
eval/phoenix/datasets/river_mile_markers/evaluation.xml.

Usage:
    uv run python scripts/verify_live.py
"""

from __future__ import annotations

import sys

# Ensure src/ is importable when run from the repo root.
sys.path.insert(0, "src")

from usace_iwr_server.utils import (  # noqa: E402
    RiverMileError,
    build_where,
    count_geometry,
    count_where,
    geojson_to_esri,
    query_geometry,
    query_where,
)


def _hr(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    try:
        _hr("Total markers on RED river (count_where)")
        red_total = count_where(build_where(river_name="RED"))
        print("RED total:", red_total)

        _hr("RED markers mile 100..120 (count_where)")
        red_100_120 = count_where(build_where(river_name="RED", mile_min=100, mile_max=120))
        print("RED 100..120:", red_100_120)

        _hr("First 5 RED markers ordered by MILE (query_where)")
        page = query_where(build_where(river_name="RED"), limit=5, offset=0)
        print("total:", page.total_count, "returned:", page.count, "has_more:", page.has_more)
        for m in page.features:
            print(" ", m)

        _hr("Nearest to (31.453, -92.709) within 5km (query_geometry buffered point)")
        gj, gtype = geojson_to_esri({"type": "Point", "coordinates": [-92.709, 31.453]})
        near = query_geometry(gj, gtype, distance=5000.0, return_geometry=True)
        print("candidates:", near.count)
        for m in near.features[:5]:
            print(" ", m)

        _hr("Count within 2km of (31.453, -92.709) (count_geometry buffered)")
        c2k = count_geometry(gj, gtype, distance=2000.0)
        print("count within 2km:", c2k)

        _hr("BBox (-92.72,31.40)-(-92.66,31.46) markers (query_geometry)")
        bgj, btype = geojson_to_esri(
            {"type": "BoundingBox", "bbox": [-92.72, 31.40, -92.66, 31.46]}
        )
        bbox = query_geometry(bgj, btype, return_geometry=False)
        print("bbox count:", bbox.count)
        for m in bbox.features:
            print(" ", m)

        print("\nALL LIVE CHECKS COMPLETED — update evaluation.xml TODO_VERIFY answers above.")
        return 0

    except RiverMileError as exc:
        print(f"\nLIVE CHECK FAILED (service unreachable or error): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
