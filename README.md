# Weather Forecast Docker Application

This Docker application fetches local and marine weather forecasts for Alaska's Pribilof Islands - St. Paul Island (99660) and St. George Island (99591) - using the NOAA/NWS API.

## Features

- **Local Forecasts**: 7-day weather forecasts for both Pribilof Islands
- **Marine Forecasts**: Marine weather for Pribilof Islands Nearshore Waters (PKZ766)
- **Automatic Updates**: Configurable update interval (default: 1 hour)
- **Data Persistence**: Saves forecasts in both JSON and text formats
- **Separate Files**: Individual files for each island and marine forecasts
- **Free API**: Uses NOAA's free National Weather Service API and text products

## Configuration

Environment variables (set in docker-compose.yml):

- `ZIP_CODES`: Comma-separated list of zip codes (default: "99660,99591")
- `UPDATE_INTERVAL`: Update interval in seconds (default: 3600 = 1 hour). NWS serves the forecast with a one-hour cache, so a shorter interval only returns the same answer.
- `TZ`: Timezone (set to: America/Anchorage). All times written by the service use this named zone, so the switch between AKST and AKDT is automatic.
- `USER_AGENT`: How the service identifies itself to NWS (default: `weather-forecast-collector/1.1`). NWS asks for an app name plus a contact.
- `NTFY_URL`, `NTFY_TOPIC`, `NTFY_TOKEN`: Where failure alerts are pushed. Alerts are skipped if URL or topic is unset. The ntfy server on this host needs the token.
- `STALE_FORECAST_HOURS` (default 24), `FETCH_RETRIES` (default 3), `POINTS_CACHE_SECONDS` (default 86400), `DATA_DIR` (default `/data`): rarely need changing.
- `RUN_ONCE=1`: run one cycle and exit, for testing against a scratch data folder.
- `ALERT_AFTER_FAILURES` (default 3): cycles in a row a source-side problem must last before one alert is pushed.
- `CONNECTIVITY_PROBES` (default `1.1.1.1:443,8.8.8.8:53`): hosts tried with a bare TCP connect to decide whether our own internet is up.

## Behaviour worth knowing

- **Timestamps** in the JSON are Alaska time with the UTC offset, for example `2026-11-16T17:48:11-09:00` (`-08:00` in summer).
- **Each island's JSON** holds `local_forecast` (7 periods), `hourly_forecast` (24 hours) and `marine_forecast`.
- **Writes are atomic**: each file is written to `<name>.tmp` and renamed, so readers never see a partial file.
- **On a failed fetch** the previous island forecast is kept, with its old timestamp, instead of being replaced by an empty one.
- **Failures are diagnosed** (`diagnose.py`) as `local_network` (our internet), `source_down` (NWS not answering), `source_stale` (NWS answering with an old forecast) or `our_error` (format changed, URL gone, refused). The cause is written to `forecast_health.json`, `forecast_report.txt` and the alert. Our own fault alerts at once; a source-side problem alerts once after three cycles; an internet outage here is only summarised when the link returns.
- **Container health** (`docker ps`) is healthy while `latest_forecast.json` is newer than two update intervals plus ten minutes.
- **Readers on this host**: the hourly cron job `pribiloftraffic/scripts/update_forecast_data.sh` copies three files into the webroot as `snp_forecast.json`, `stg_forecast.json` and `marine_forecast.json`; `pribobs_commentary.py` reads `latest_forecast.txt` directly. Do not rename the output files.

## Output Files

The application saves forecast data to the `/data` volume:

### Combined Forecasts
- `/data/latest_forecast.json`: All forecast data in JSON format
- `/data/latest_forecast.txt`: All forecasts in human-readable format

### Individual Island Forecasts
- `/data/st._paul_island_99660.json`: St. Paul Island data (JSON)
- `/data/st._paul_island_99660.txt`: St. Paul Island forecast (text)
- `/data/st._george_island_99591.json`: St. George Island data (JSON)
- `/data/st._george_island_99591.txt`: St. George Island forecast (text)

### Marine Forecasts
- `/data/pribilof_island_waters.json`: Marine forecast data (JSON)
- `/data/pribilof_island_waters.txt`: Marine forecast (text)

## Marine Zone Covered

- **PKZ766**: Pribilof Islands Nearshore Waters (Bering Sea)

## Usage

### Start the service:
```bash
docker-compose up -d weather-forecast
```

### View logs:
```bash
docker-compose logs -f weather-forecast
```

### View API health status:
```bash
./view_status.sh
```

### Stop the service:
```bash
docker-compose down weather-forecast
```

## Health Monitoring

The application includes comprehensive health monitoring to ensure data integrity:

- **API availability tracking** - Records every fetch attempt
- **Stale forecast detection** - Alerts while the latest forecast is more than 24 hours old
- **Outage detection** - Tracks when NWS API is down
- **Uptime statistics** - Calculates reliability percentage
- **Status reports** - Generates `forecast_report.txt`
- **Never serves fake data** - Only real-time NOAA forecasts

### View Status Report

```bash
cat data/forecast_report.txt
```

Or use the helper script:
```bash
./view_status.sh
```

The report shows:
- Current API status (online/offline/stale)
- Uptime percentage per location
- Stale forecast warnings
- Recent outage history
- Active alerts

### View forecasts:

**View all forecasts (combined):**
```bash
cat /opt/dockers/weather-forecast/data/latest_forecast.txt
```

**View St. Paul Island forecast:**
```bash
cat /opt/dockers/weather-forecast/data/st._paul_island_99660.txt
```

**View St. George Island forecast:**
```bash
cat /opt/dockers/weather-forecast/data/st._george_island_99591.txt
```

**View marine forecast (Pribilof Islands Nearshore Waters):**
```bash
cat /opt/dockers/weather-forecast/data/pribilof_island_waters.txt
```

### Stop the service:
```bash
docker-compose down weather-forecast
```

## Data Sources

This application uses multiple NOAA data sources:

- **Local Forecasts**: NOAA National Weather Service API
  - API: https://api.weather.gov
  - No API key required
  - Documentation: https://www.weather.gov/documentation/services-web-api

- **Marine Forecasts**: NOAA Text Products
  - Source: https://tgftp.nws.noaa.gov/data/raw/fz/fzak52.pafc.cwf.alu.txt
  - Updates: Multiple times daily
  - Includes Small Craft Advisories and marine conditions

## Locations

- **St. Paul Island (99660)**: 57.1253°N, 170.2806°W
- **St. George Island (99591)**: 56.5983°N, 169.5464°W
- **Marine Zone PKZ766**: Pribilof Islands Nearshore Waters (Bering Sea)
