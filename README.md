# mcp-server-usace-iwr

An MCP (Model Context Protocol) server that wraps the U.S. Army Corps of
Engineers (USACE) Institute for Water Resources (IWR) **River Mile Marker**
ArcGIS Feature Service, letting an LLM locate river mile markers on navigable
U.S. rivers and answer "what river mile am I at?" style questions.

- **Dataset:** [USACE River Mile Markers](https://www.arcgis.com/home/item.html?id=604cdc08fe7d43cb90a0584a0b198875)
- **Service:** `https://services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/usace_river_mile_markers/FeatureServer/0`
- **Auth:** none (public service)
- **CRS:** WGS84 (EPSG:4326) decimal degrees

## Tools

| Tool | Purpose |
|------|---------|
| `usace_rivermile_nearest` | Return the single closest marker to a lat/lon (with distance + bearing). |
| `usace_rivermile_find_markers` | Find markers near a point (radius) or within a GeoJSON geometry/bbox. |
| `usace_rivermile_query` | Filter markers by river name and/or mile-value range, with pagination. |

All tools are read-only and return provenance (source agency, dataset, service
URL, layer, CRS, retrieval time).

## Layer fields

`name`, `LONGITUDE1`, `LATITUDE1`, `MILE`, `RIVER_CODE`, `RIVER_NAME`,
`RIVER_NUMB`, `SOURCE`.

## Running locally (stdio)

```bash
uv sync
uv run python -m usace_iwr_server.app
```

The server uses **stdio** transport by default. If a `PORT` (or
`DATABRICKS_APP_PORT`) environment variable is set, it serves streamable HTTP at
`/mcp` instead, with a `/health` readiness endpoint.

## Container / deployment

```bash
bash scripts/build-and-push.sh   # builds linux/amd64 and pushes to GHCR
```

## Development

```bash
uv run python -m py_compile src/usace_iwr_server/*.py src/usace_iwr_server/tools/*.py
npx @modelcontextprotocol/inspector uv run python -m usace_iwr_server.app
```
