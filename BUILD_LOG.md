# Build Log - Weather Forecast Collector

**Started**: 2024-10 (estimated from file timestamps)
**Status**: ✅ Complete and Running
**Purpose**: Automated weather forecast collection and monitoring for Alaska's Pribilof Islands

---

## The Problem I Was Solving

**What was broken or missing?**
- No automated weather forecast collection for Pribilof Islands (St. Paul and St. George)
- Had to manually check multiple NOAA websites
- Needed both local (7-day) and marine forecasts
- No API for programmatic access to current forecast data
- No health monitoring to detect when NOAA API is down or serving stale data

**Why did I need this?**
- Monitor weather conditions in remote Alaska locations
- Use cases: weather analysis, marine operations, forecast display on the website
- Need consistent data format for downstream applications
- Want local cache to avoid repeated NOAA API calls

**What was I trying to accomplish?**
- Automated collection of weather forecasts for St. Paul Island (99660) and St. George Island (99591)
- Local forecasts (7-day) from NOAA/NWS API
- Marine forecasts (PKZ766 - Pribilof Islands Nearshore Waters) from NOAA text products
- Health monitoring to detect API outages and stale forecasts
- Multiple output formats (JSON + human-readable text)
- Separate files per island for targeted access
- Optional syncing to web directory for public access

**Coverage**: 2 Alaska islands + 1 marine zone (Bering Sea)

---

## Critical Decisions & Why

### Decision 1: Dual NOAA Data Sources

**What I chose**: NOAA/NWS API + NOAA text products
**Why**:
- **Local forecasts**: NOAA National Weather Service API (api.weather.gov)
  - Free, no API key required
  - Returns structured JSON
  - 7-day forecasts with detailed periods
- **Marine forecasts**: NOAA text products (tgftp.nws.noaa.gov)
  - Marine zones (PKZ766) not available via API
  - Text parsing required but more complete
  - Includes Small Craft Advisories

**How it works**:
```python
# Local forecast (API)
BASE_URL = "https://api.weather.gov"
url = f"{BASE_URL}/points/{lat},{lon}"
forecast_url = response.json()['properties']['forecast']

# Marine forecast (text product)
text_url = "https://tgftp.nws.noaa.gov/data/raw/fz/fzak52.pafc.cwf.alu.txt"
# Parse text to extract PKZ766 section
```

**Why not alternatives**:
- Weather.com API: Requires paid API key
- OpenWeather: Less accurate for Alaska
- Single source: Marine zones require text products

**Tradeoff**: More complex (two sources) but complete coverage

### Decision 2: Hardcoded Coordinates for Zip Codes

**What I chose**: Hardcoded mapping of zip codes to lat/lon
**Why**:
- Only two zip codes (99660, 99591)
- Coordinates don't change
- Avoids dependency on geocoding API
- Faster (no extra API call)

**Implementation**:
```python
alaska_zips = {
    '99660': {'lat': 57.1253, 'lon': -170.2806, 'city': 'St. Paul Island'},
    '99591': {'lat': 56.5983, 'lon': -169.5464, 'city': 'St. George Island'}
}
```

**Alternatives considered**:
- Geocoding API (Google, Mapbox): Extra dependency, rate limits
- Database: Overkill for 2 locations
- ENV variables: Hardcoded is simpler

**Would I choose differently?**:
- If adding many zip codes, would use external geocoding
- For 2 locations, hardcoded is perfect

### Decision 3: Comprehensive Health Monitoring

**What I chose**: Custom ForecastMonitor class with detailed tracking
**Why**:
- Need to know when NOAA API is down
- Detect stale forecasts (>12 hours old)
- Track uptime percentage per location
- Alert on issues immediately
- Never serve fake or outdated data

**Features**:
- Records every fetch attempt (success/failure)
- Detects current outages
- Tracks outage history
- Calculates uptime percentage
- Generates human-readable status reports
- Saves health data to forecast_health.json

**Monitoring thresholds**:
- Stale forecast: >12 hours old
- Stale data warning: No fresh data for >2 hours
- Outage: API returns errors

**File**: `monitor.py` (356 lines)

**Why not alternatives**:
- Basic logging: Can't track uptime or outages
- External monitoring service: Adds dependency
- No monitoring: Can't detect issues

**Tradeoff**: More code, but critical reliability insight

### Decision 4: Multiple Output Formats

**What I chose**: JSON + human-readable text, combined + per-island files
**Why**:
- **JSON**: For programmatic access (APIs, web apps)
- **Text**: For humans, logs, quick checks
- **Combined**: All data in one place
- **Per-island**: Targeted access without parsing

**Output files**:
```
/data/
├── latest_forecast.json          # All forecasts (JSON)
├── latest_forecast.txt           # All forecasts (text)
├── st._paul_island_99660.json    # St. Paul only (JSON)
├── st._paul_island_99660.txt     # St. Paul only (text)
├── st._george_island_99591.json  # St. George only (JSON)
├── st._george_island_99591.txt   # St. George only (text)
├── pribilof_island_waters.json   # Marine forecast (JSON)
├── pribilof_island_waters.txt    # Marine forecast (text)
├── forecast_health.json          # Health monitoring data
└── forecast_report.txt           # Human-readable status report
```

**Benefits**:
- Flexibility for different use cases
- Easy debugging (just cat the .txt file)
- Web-friendly (JSON for JavaScript)

### Decision 5: Update Interval

**What I chose**: 3600 seconds (1 hour)
**Why**:
- NOAA updates forecasts every 1-6 hours
- 1 hour ensures reasonably fresh data
- Doesn't overwhelm NOAA API
- Balanced freshness vs. API calls

**Configurable**:
```yaml
environment:
  - UPDATE_INTERVAL=3600
```

### Decision 6: Web Directory Sync (Optional)

**What I chose**: Manual sync script (sync_to_web.sh)
**Why**:
- Needed to serve forecasts via web server
- Docker data directory not directly accessible
- Renames files for web consistency (snp_forecast.json, stg_forecast.json)

**Script**: `sync_to_web.sh`
**Destination**: `<web-root>/data`

**Why not automated**:
- Web server might not always exist
- Gives control over when to publish
- Could be added to cron if needed

---

## Build Timeline & Gotchas

### Day 1: Research & Initial API Integration

**What I did**:
- Researched NOAA weather APIs
- Found api.weather.gov for local forecasts
- Wrote initial collection logic for single zip code

**Gotcha #1**: NOAA API requires User-Agent header
- **Symptom**: API returned 403 Forbidden
- **Root cause**: NOAA blocks requests without User-Agent
- **Solution**: Added custom User-Agent header
- **Code**:
  ```python
  USER_AGENT = "WeatherForecastApp/1.0"
  session.headers.update({'User-Agent': USER_AGENT})
  ```
- **Time wasted**: 30 minutes

**Gotcha #2**: API uses points endpoint for forecast URLs
- **Symptom**: Couldn't find direct forecast endpoint
- **Root cause**: Must query /points/{lat},{lon} first to get forecast URL
- **Solution**: Two-step process
  1. GET /points/{lat},{lon} → returns forecast URL
  2. GET {forecast_url} → returns actual forecast
- **Pattern**: Standard NOAA API design

### Day 2: Marine Forecast Integration

**What I did**:
- Tried to find marine forecast in API
- Discovered marine zones only in text products
- Wrote text parser for PKZ766

**Gotcha #3**: Marine forecasts not available via JSON API
- **Symptom**: No marine data in API response
- **Root cause**: Marine zones (PKZ766) only in text products
- **Solution**: Fetch and parse text product from tgftp.nws.noaa.gov
- **URL**: https://tgftp.nws.noaa.gov/data/raw/fz/fzak52.pafc.cwf.alu.txt
- **Time wasted**: 2 hours (searching for non-existent API endpoint)

**Gotcha #4**: Text parsing is fragile
- **Symptom**: Sometimes failed to extract PKZ766 section
- **Root cause**: Text format varies slightly
- **Solution**: Robust parsing logic
  - Look for 'PKZ766' line
  - Continue until next zone or '$$' marker
  - Handle edge cases (empty lines, formatting)
- **Code**: Lines 102-127 in app.py

### Day 3: Health Monitoring System

**What I did**:
- Created ForecastMonitor class
- Added tracking for attempts, successes, failures
- Implemented stale forecast detection

**Gotcha #5**: Timestamp parsing is tricky
- **Symptom**: Couldn't calculate forecast age
- **Root cause**: ISO timestamps with 'Z' suffix not directly parseable
- **Solution**: Replace 'Z' with '+00:00' before parsing
- **Pattern**:
  ```python
  forecast_dt = datetime.fromisoformat(forecast_time.replace('Z', '+00:00'))
  ```

**What worked**:
- Uptime percentage calculation
- Outage detection and history tracking
- Alert generation (offline, stale, warning states)

### Day 4: Multiple Output Formats

**What I did**:
- Added text formatting alongside JSON
- Created per-island file outputs
- Generated combined forecast file

**Gotcha #6**: File naming with spaces and underscores
- **Symptom**: Inconsistent file names
- **Root cause**: Using location name directly in filename
- **Solution**: Convert to lowercase, replace spaces with underscores
- **Pattern**:
  ```python
  island_name = zip_data.get('location', zip_code).replace(' ', '_').lower()
  filename = f'/data/{island_name}_{zip_code}.json'
  ```
- **Note**: Results in st._paul_island_99660.json (period after st intentional)

### Day 5: Docker Integration & Web Sync

**What I did**:
- Created Dockerfile with Python 3.11-slim
- Added docker-compose.yml entry
- Created sync_to_web.sh for public access

**What worked**:
- Simple Dockerfile (no complex dependencies)
- Volume mount for /data directory
- Configurable via environment variables

---

## External Dependencies (CRITICAL)

### Dependency 1: NOAA National Weather Service API

- **Status**: ✅ REQUIRED (for local forecasts)
- **Provider**: NOAA/NWS
- **Base URL**: https://api.weather.gov
- **Endpoints used**:
  - `/points/{lat},{lon}` - Get forecast URLs
  - `/forecast/{gridpoint}` - Get 7-day forecast
- **Update frequency**: Every 1-6 hours
- **Rate limits**: None documented (User-Agent required)
- **Documentation**: https://www.weather.gov/documentation/services-web-api

**Query pattern**:
```bash
# Step 1: Get forecast URL
curl -H "User-Agent: WeatherForecastApp/1.0" \
  "https://api.weather.gov/points/57.1253,-170.2806"

# Step 2: Fetch forecast
curl -H "User-Agent: WeatherForecastApp/1.0" \
  "https://api.weather.gov/gridpoints/AFG/25,88/forecast"
```

**Check if available**:
```bash
curl -H "User-Agent: test" "https://api.weather.gov/points/57.1253,-170.2806"
# Should return JSON with forecast URLs
```

**If down**:
- **Status page**: https://www.weather.gov/
- **Impact**: No local forecast collection, last data remains available
- **Fallback**: Monitoring system detects outage, keeps serving last good data
- **Recovery**: Automatic when service returns

### Dependency 2: NOAA Text Products Server

- **Status**: ✅ REQUIRED (for marine forecasts)
- **Provider**: NOAA/NWS
- **Base URL**: https://tgftp.nws.noaa.gov
- **Product**: fzak52.pafc.cwf.alu.txt (Alaska marine forecasts)
- **Update frequency**: Multiple times daily
- **Rate limits**: None documented
- **Format**: Plain text (requires parsing)

**Query format**:
```bash
curl "https://tgftp.nws.noaa.gov/data/raw/fz/fzak52.pafc.cwf.alu.txt"
# Returns text product with PKZ766 section
```

**If down**:
- **Impact**: No marine forecast collection
- **Fallback**: Last collected marine forecast remains
- **Recovery**: Automatic when service returns

### Dependency 3: Internet Connection

- **Status**: ✅ REQUIRED
- **Bandwidth**: Minimal (~10 KB per collection, ~240 KB/day)
- **Latency tolerance**: 10 second timeout per API call
- **If down**: Collection fails, logged but doesn't crash

### Optional Dependency: Web Server (for sync)

- **Status**: ⚠️ OPTIONAL
- **Path**: <web-root>/data
- **Purpose**: Serve forecasts via web server
- **If missing**: sync_to_web.sh fails but collector still works

---

## Architecture Overview

```
NOAA Weather Services                    Docker Container
┌───────────────────────────┐           ┌─────────────────────────────┐
│ api.weather.gov           │           │                             │
│ /points → /forecast       │──GET(1h)─▶│  ┌───────────────────────┐  │
│                           │           │  │ app.py                │  │
└───────────────────────────┘           │  │ WeatherForecastFetcher│  │
                                        │  │                       │  │
┌───────────────────────────┐           │  │ - Fetch local         │  │
│ tgftp.nws.noaa.gov        │           │  │ - Fetch marine        │  │
│ /data/raw/fz/...cwf.txt   │──GET(1h)─▶│  │ - Parse PKZ766        │  │
│ (PKZ766 text product)     │           │  │ - Format outputs      │  │
└───────────────────────────┘           │  └───────────────────────┘  │
                                        │            ↓                 │
                                        │  ┌───────────────────────┐  │
                                        │  │ monitor.py            │  │
                                        │  │ ForecastMonitor       │  │
                                        │  │                       │  │
                                        │  │ - Track attempts      │  │
                                        │  │ - Detect outages      │  │
                                        │  │ - Check staleness     │  │
                                        │  │ - Generate reports    │  │
                                        │  └───────────────────────┘  │
                                        │            ↓                 │
                                        │      /data/ (volume)         │
                                        │      ├── *.json              │
                                        │      ├── *.txt               │
                                        │      └── forecast_health     │
                                        └─────────────────────────────┘
                                                    ↓
                                           sync_to_web.sh (manual)
                                                    ↓
                                        <web-root>/data
                                        ├── snp_forecast.json
                                        ├── stg_forecast.json
                                        └── marine_forecast.json
```

### Components

**WeatherForecastFetcher** (app.py):
- Infinite loop with UPDATE_INTERVAL delay
- Fetches from both NOAA sources
- Formats multiple output files
- Calls ForecastMonitor for health tracking

**ForecastMonitor** (monitor.py):
- Tracks all fetch attempts
- Records successes and failures
- Detects outages (current + history)
- Calculates uptime percentage
- Generates status reports
- Checks forecast freshness (>12 hours = stale)

**Data Storage**:
- Docker volume: /data
- 10 output files per collection cycle
- JSON + text formats
- Health monitoring data persisted

---

## Output Files Details

### Combined Files

**latest_forecast.json** (~5-10 KB):
```json
{
  "99660": {
    "zip_code": "99660",
    "location": "St. Paul Island",
    "coordinates": {"lat": 57.1253, "lon": -170.2806},
    "timestamp": "2025-01-12T10:30:00",
    "local_forecast": {
      "updated": "2025-01-12T09:00:00Z",
      "periods": [...]
    },
    "marine_forecast": {
      "PKZ766": {...}
    }
  },
  "99591": {...}
}
```

**latest_forecast.txt** (~2-3 KB):
Human-readable formatted version with all forecasts

### Per-Island Files

- `st._paul_island_99660.json` - St. Paul data only
- `st._paul_island_99660.txt` - St. Paul formatted
- `st._george_island_99591.json` - St. George data only
- `st._george_island_99591.txt` - St. George formatted

### Marine Files

- `pribilof_island_waters.json` - PKZ766 marine forecast
- `pribilof_island_waters.txt` - PKZ766 formatted text

### Health Monitoring Files

**forecast_health.json** (~1-2 KB):
```json
{
  "locations": {
    "99660": {
      "total_attempts": 245,
      "successful_attempts": 243,
      "failed_attempts": 2,
      "last_success": "2025-01-12T10:30:00",
      "current_outage_start": null,
      "outage_history": [],
      "last_forecast_time": "2025-01-12T09:00:00Z",
      "stale_forecast_count": 0
    }
  }
}
```

**forecast_report.txt** (~1 KB):
Human-readable status report showing online/offline status, uptime %, alerts

---

## "Lost Everything" Rebuild Checklist

1. [ ] Create app.py:
   - WeatherForecastFetcher class
   - Hardcoded Alaska zip coordinates (99660, 99591)
   - Fetch from api.weather.gov (two-step: points → forecast)
   - Fetch from tgftp.nws.noaa.gov (parse PKZ766 text)
   - Format multiple outputs (JSON + text, combined + per-island)
   - Must include User-Agent header
   - Loop with UPDATE_INTERVAL

2. [ ] Create monitor.py:
   - ForecastMonitor class
   - Track attempts (success/failure)
   - Detect outages (current + history)
   - Check forecast staleness (>12 hours)
   - Calculate uptime percentage
   - Generate status report
   - Save to forecast_health.json and forecast_report.txt

3. [ ] Create requirements.txt:
   ```
   requests==2.31.0
   ```

4. [ ] Create Dockerfile:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY app.py .
   COPY monitor.py .
   RUN mkdir -p /data
   CMD ["python", "-u", "app.py"]
   ```

5. [ ] Add to docker-compose.yml:
   ```yaml
   weather-forecast:
     build: ./weather-forecast
     container_name: weather-forecast
     restart: always
     volumes:
       - ./weather-forecast/data:/data
     environment:
       - TZ=America/Anchorage
       - ZIP_CODES=99660,99591
       - UPDATE_INTERVAL=3600
   ```

6. [ ] Create optional helper scripts:
   - view_status.sh: Display forecast_report.txt
   - sync_to_web.sh: Copy forecasts to <web-root>/data

7. [ ] Test NOAA APIs:
   ```bash
   # Test local forecast API
   curl -H "User-Agent: test" \
     "https://api.weather.gov/points/57.1253,-170.2806"

   # Test marine text product
   curl "https://tgftp.nws.noaa.gov/data/raw/fz/fzak52.pafc.cwf.alu.txt" \
     | grep -A 20 PKZ766
   ```

8. [ ] Build and start:
   ```bash
   docker compose build weather-forecast
   docker compose up -d weather-forecast
   ```

9. [ ] Verify:
   ```bash
   # Check logs
   docker compose logs -f weather-forecast

   # View forecasts
   cat data/latest_forecast.txt
   cat data/pribilof_island_waters.txt

   # View health status
   cat data/forecast_report.txt
   # OR
   ./view_status.sh
   ```

**Estimated rebuild time**: 4-6 hours

**Hardest parts**:
- Marine forecast text parsing (PKZ766 extraction)
- Two-step NOAA API (points → forecast)
- Health monitoring with stale detection

---

## What I Learned / Would Do Differently

### Lessons Learned:

1. **Lesson**: User-Agent header is mandatory for NOAA API
   - **Context**: API blocks requests without User-Agent
   - **Solution**: Always include custom User-Agent header
   - **Impact**: No 403 errors

2. **Lesson**: Marine forecasts require text parsing
   - **Context**: No JSON API for marine zones
   - **Reality**: Must parse text products
   - **Impact**: More fragile but works

3. **Lesson**: Health monitoring is essential
   - **Context**: Need to know when API is down or stale
   - **Pattern**: Track every attempt, calculate uptime, detect outages
   - **Benefit**: Confidence in data reliability

4. **Lesson**: Multiple output formats increase usability
   - **Context**: Different consumers need different formats
   - **Solution**: JSON (APIs) + text (humans)
   - **Benefit**: Flexible, easy debugging

### Known Technical Debt:

1. **Issue**: Hardcoded zip code coordinates
   - **Why**: Only 2 locations, simple
   - **Impact**: Can't easily add new locations
   - **Fix when**: If adding more zip codes
   - **Solution**: Use geocoding API or database

2. **Issue**: Text parsing for marine forecasts
   - **Why**: No JSON API available
   - **Impact**: Fragile if text format changes
   - **Fix when**: If parsing breaks frequently
   - **Solution**: Contact NOAA about JSON marine API

3. **Issue**: Manual web sync (sync_to_web.sh)
   - **Why**: Simple, gives control
   - **Impact**: Must run manually or via cron
   - **Fix when**: If web sync needed immediately
   - **Solution**: Add to main loop or use inotify

### Future Improvements:

- [ ] Add geocoding for dynamic zip codes
- [ ] Expose REST API for forecast queries
- [ ] Add web UI for viewing forecasts
- [ ] Email/SMS alerts on weather conditions
- [ ] Historical forecast storage and trends
- [ ] Integration with weather forecast accuracy tracking

---

## Related Projects / Resources

### NOAA Documentation:
- **NWS API**: https://www.weather.gov/documentation/services-web-api
- **Marine text products**: https://tgftp.nws.noaa.gov/
- **Alaska marine zones**: https://www.weather.gov/afc/zone

### Similar Projects:
- noaa-data-collector: Collects buoy and tide data (sibling project)
- alaska-metar-collector: Collects aviation weather (sibling project)

---

## Maintenance Log

### 2024-10: Initial Creation
- Built forecast collector with dual NOAA sources
- Added health monitoring system
- Deployed to production
- Collecting St. Paul and St. George Islands

### 2026-01-12: Documentation Update
- Created BUILD_LOG.md (retroactive)

---

## Quick Reference

### Daily Operations:
```bash
# Status
docker compose ps weather-forecast

# Logs
docker compose logs -f weather-forecast

# Restart
docker compose restart weather-forecast
```

### View Forecasts:
```bash
# Combined forecast
cat data/latest_forecast.txt

# St. Paul Island
cat data/st._paul_island_99660.txt

# St. George Island
cat data/st._george_island_99591.txt

# Marine forecast
cat data/pribilof_island_waters.txt

# Health status
cat data/forecast_report.txt
# OR
./view_status.sh
```

### Sync to Web (Optional):
```bash
cd weather-forecast
sudo ./sync_to_web.sh
```

### Troubleshooting:
```bash
# Check NOAA API (local forecasts)
curl -H "User-Agent: test" \
  "https://api.weather.gov/points/57.1253,-170.2806"

# Check NOAA text products (marine forecasts)
curl "https://tgftp.nws.noaa.gov/data/raw/fz/fzak52.pafc.cwf.alu.txt" \
  | grep -A 30 PKZ766

# Check data files
ls -lh data/

# Check health monitoring
cat data/forecast_health.json | jq

# Check logs for errors
docker compose logs --tail=100 weather-forecast | grep -i error
```

---

**Status**: ✅ Running continuously since October 2025
**Uptime**: Excellent (auto-restart on failure)
**Update Frequency**: 1 hour
**Data Freshness**: <2 hours (typically <1 hour)

**Maintained by**: PribilofTraffic
**Created**: 2025-10
**Last updated**: 2026-11-16
