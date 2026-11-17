#!/bin/bash
# Sync weather forecast data from Docker to web directories
#
# Optional: only for setups that copy the forecast files into a web root
# instead of linking to them.
#
# Inputs (environment):
#   WEB_DATA     required: the web server's data folder to copy into
#   DOCKER_DATA  optional: the collector's data folder (default: ./data
#                next to this script)
# Output: snp_forecast.json, stg_forecast.json, marine_forecast.json in WEB_DATA

DOCKER_DATA="${DOCKER_DATA:-$(cd "$(dirname "$0")" && pwd)/data}"
WEB_DATA="${WEB_DATA:?Set WEB_DATA to the web server data folder, e.g. WEB_DATA=/path/to/site/data $0}"

# Ensure web data directory exists
mkdir -p "$WEB_DATA"

# Copy and rename St. Paul Island forecast
if [ -f "$DOCKER_DATA/st._paul_island_99660.json" ]; then
    cp "$DOCKER_DATA/st._paul_island_99660.json" "$WEB_DATA/snp_forecast.json"
    echo "$(date): Synced St. Paul forecast"
fi

# Copy and rename St. George Island forecast
if [ -f "$DOCKER_DATA/st._george_island_99591.json" ]; then
    cp "$DOCKER_DATA/st._george_island_99591.json" "$WEB_DATA/stg_forecast.json"
    echo "$(date): Synced St. George forecast"
fi

# Copy marine forecast
if [ -f "$DOCKER_DATA/pribilof_island_waters.json" ]; then
    cp "$DOCKER_DATA/pribilof_island_waters.json" "$WEB_DATA/marine_forecast.json"
    echo "$(date): Synced marine forecast"
fi

# Set proper permissions
chown www-data:www-data "$WEB_DATA"/*.json 2>/dev/null
chmod 644 "$WEB_DATA"/*.json 2>/dev/null

echo "$(date): Weather forecast sync complete"
