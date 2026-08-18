import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from usace_iwr_server.tools import register_tools
from usace_iwr_server.routes import register_routes

load_dotenv()  # loads .env before any code reads env vars

# Initialize FastMCP server
mcp = FastMCP(
    "usace_iwr_mcp",
    instructions=(
        "Wraps the U.S. Army Corps of Engineers (USACE) Institute for Water Resources (IWR) "
        "River Mile Marker ArcGIS Feature Service so an LLM can locate river mile markers "
        "on navigable U.S. rivers and answer 'what river mile am I at?' style questions.\n\n"
        "TOOL SELECTION GUIDE:\n"
        "- Closest marker to a coordinate / 'what river mile is here?' -> usace_rivermile_nearest\n"
        "- Markers near a point (with radius) or inside a geometry/bbox -> usace_rivermile_find_markers\n"
        "- Filter markers by river name and/or mile-value range (list, paginate) -> usace_rivermile_query\n\n"
        "CONVENTIONS:\n"
        "- All coordinates are WGS84 decimal degrees (lat, lon). Convert addresses/places to "
        "coordinates first.\n"
        "- Distances are in meters. Radii default to 5 km (find) and 50 km (nearest).\n"
        "- MILE is the river mile value; RIVER_NAME is the river (e.g. 'RED', 'MISSISSIPPI'); "
        "RIVER_NAME matching is case-insensitive substring.\n"
        "- Geometry input is a GeoJSON string: Point, MultiPoint, LineString, MultiLineString, "
        'Polygon, MultiPolygon, or BoundingBox shorthand '
        '{"type": "BoundingBox", "bbox": [minLon, minLat, maxLon, maxLat]}.\n'
        "- Results include provenance (source agency, dataset, service URL, layer, CRS, retrieval time).\n"
        "- No authentication required -- the service is publicly accessible."
    ),
)

# Register custom tools
register_tools(mcp)

# Register custom routes
register_routes(mcp)

if __name__ == "__main__":
    port_env = os.getenv("DATABRICKS_APP_PORT") or os.getenv("PORT")
    if port_env:
        mcp.run(transport="http", host="0.0.0.0", port=int(port_env), path="/mcp")
    else:
        mcp.run(transport="stdio")
