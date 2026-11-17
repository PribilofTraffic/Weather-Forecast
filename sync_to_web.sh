#!/bin/bash
# Sync weather forecast data from Docker to web directories

DOCKER_DATA="/opt/dockers/weather-forecast/data"
WEB_DATA="/var/www/html/pribiloftraffic/data"

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
