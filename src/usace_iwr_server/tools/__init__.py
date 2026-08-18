from . import find_markers, nearest_marker, query_markers


def register_tools(mcp):
    """Register all tools with the MCP server."""
    find_markers.register(mcp)
    nearest_marker.register(mcp)
    query_markers.register(mcp)
