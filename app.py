#!/usr/bin/env python3
"""
Weather Forecast Application
Fetches local and marine forecasts for specified zip codes using NOAA/NWS API
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
import logging
import os

import diagnose
from monitor import ForecastMonitor

# Settings (all overridable from the environment / compose file)
DATA_DIR = os.getenv('DATA_DIR', '/data')
# Local time zone. Using a named zone (not a fixed offset) means every time
# written below switches between AKST and AKDT on its own.
LOCAL_TZ = ZoneInfo(os.getenv('TZ', 'America/Anchorage'))
# NWS asks API clients to identify themselves, ideally with a contact
# (site or email). Set USER_AGENT in compose to add one.
USER_AGENT = os.getenv('USER_AGENT', 'weather-forecast-collector/1.1')
FETCH_RETRIES = int(os.getenv('FETCH_RETRIES', '3'))
# How long to reuse the NWS point -> forecast-grid lookup (default one day,
# matching the cache lifetime NWS puts on that answer).
POINTS_CACHE_SECONDS = int(os.getenv('POINTS_CACHE_SECONDS', '86400'))
NWS_API_URL = os.getenv('NWS_API_URL', 'https://api.weather.gov')
MARINE_URL = os.getenv(
    'MARINE_URL', 'https://tgftp.nws.noaa.gov/data/raw/fz/fzak52.pafc.cwf.alu.txt')


def local_now() -> datetime:
    """Current time in the local zone, with its UTC offset attached."""
    return datetime.now(LOCAL_TZ)


def atomic_write(path: str, text: str) -> None:
    """Write to a temp file, then rename over the target.

    Readers (the web server and other scripts on the host) see either the old
    file or the new one, never a half-written one. The temp file is created
    with open() so it keeps the normal 0644 mode and stays world-readable.
    """
    tmp = f"{path}.tmp"
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def write_json(path: str, data) -> None:
    atomic_write(path, json.dumps(data, indent=2))


def notify_ntfy(title, alerts, priority=None, tags='warning'):
    """Push messages to the self-hosted ntfy server. No-op if unconfigured.

    What gets pushed, and when, is decided by ForecastMonitor (one alert per
    outage, then one when it ends), not here.
    """
    url = os.getenv('NTFY_URL')
    topic = os.getenv('NTFY_TOPIC')
    if not url or not topic or not alerts:
        return
    headers = {
        'Title': title,
        'Priority': priority or os.getenv('NTFY_PRIORITY', 'high'),
        'Tags': tags,
    }
    token = os.getenv('NTFY_TOKEN')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        response = requests.post(f"{url.rstrip('/')}/{topic}",
                                 data='\n'.join(alerts).encode('utf-8'),
                                 headers=headers, timeout=10)
        if response.status_code >= 400:
            # 401/403 means NTFY_TOKEN is missing or wrong: say so instead
            # of dropping the alert silently.
            logger.warning(f"ntfy rejected the alert: HTTP {response.status_code}")
    except Exception as e:
        logger.warning(f"ntfy notify failed: {e}")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class WeatherForecastFetcher:
    """Fetches weather forecasts from NOAA/NWS API"""
    
    BASE_URL = NWS_API_URL

    def __init__(self, zip_codes: List[str]):
        self.zip_codes = zip_codes
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'application/json'
        })
        self._points_cache = {}  # (lat, lon) -> (fetched_at, urls)
        # Why each fetch failed this cycle: 'marine' or a zip code ->
        # (cause, detail), as worked out by diagnose.classify_failure().
        self.failures = {}
        self._context = None

    def _fail(self, exc: BaseException) -> None:
        """Record whose end a failure is on, for the part being fetched."""
        cause, detail = diagnose.classify_failure(exc)
        self.failures[self._context] = (cause, detail)
        logger.warning(f"Diagnosis for {self._context}: {diagnose.describe(cause, detail)}")

    def _get(self, url: str) -> requests.Response:
        """GET with a timeout and a few retries (2s, 4s, ... between tries).

        Retries network errors and 5xx answers; a 4xx is returned at once
        because asking again will not change it.
        """
        last_error = None
        for attempt in range(1, FETCH_RETRIES + 1):
            try:
                response = self.session.get(url, timeout=15)
                if response.status_code < 500:
                    return response
                last_error = requests.HTTPError(
                    f"{response.status_code} from {url}", response=response)
            except requests.RequestException as e:
                last_error = e
            if attempt < FETCH_RETRIES:
                time.sleep(2 * attempt)
        raise last_error

    def get_coordinates_from_zip(self, zip_code: str) -> Optional[Dict]:
        """Get latitude and longitude from zip code using geocoding API"""
        try:
            # Using a simple geocoding approach via NWS
            # For Alaska zip codes, we'll use known coordinates
            alaska_zips = {
                '99660': {'lat': 57.1253, 'lon': -170.2806, 'city': 'St. Paul Island'},
                '99591': {'lat': 56.5983, 'lon': -169.5464, 'city': 'St. George Island'}
            }
            
            if zip_code in alaska_zips:
                return alaska_zips[zip_code]
            
            logger.warning(f"Zip code {zip_code} not in predefined list")
            return None
            
        except Exception as e:
            logger.error(f"Error getting coordinates for {zip_code}: {e}")
            return None
    
    def get_forecast_urls(self, lat: float, lon: float) -> Optional[Dict]:
        """Get forecast URLs from NWS points endpoint.

        The answer (which forecast grid cell a point falls in) almost never
        changes and NWS itself marks it cacheable for a day, so it is looked
        up once a day rather than every cycle.
        """
        cache_key = (lat, lon)
        cached = self._points_cache.get(cache_key)
        if cached and time.time() - cached[0] < POINTS_CACHE_SECONDS:
            return cached[1]
        try:
            url = f"{self.BASE_URL}/points/{lat},{lon}"
            response = self._get(url)
            response.raise_for_status()
            data = response.json()

            urls = self._forecast_urls_from(data)
            self._points_cache[cache_key] = (time.time(), urls)
            return urls
        except Exception as e:
            logger.error(f"Error getting forecast URLs for {lat},{lon}: {e}")
            if not cached:
                self._fail(e)
            # If the lookup fails, an older answer is still better than none.
            return cached[1] if cached else None

    @staticmethod
    def _forecast_urls_from(data: Dict) -> Dict:
        return {
            'forecast': data['properties'].get('forecast'),
            'forecast_hourly': data['properties'].get('forecastHourly'),
            'forecast_grid_data': data['properties'].get('forecastGridData'),
            'observation_stations': data['properties'].get('observationStations'),
            'county': data['properties'].get('county'),
            'fire_weather_zone': data['properties'].get('fireWeatherZone')
        }

    def get_forecast(self, forecast_url: str) -> Optional[Dict]:
        """Get the actual forecast data"""
        try:
            response = self._get(forecast_url)
            response.raise_for_status()
            data = response.json()
            properties = data['properties']
            # NWS renamed 'updated' to 'updateTime'; accept either so the
            # 'updated' field in our output is filled again.
            if not properties.get('updated'):
                properties['updated'] = properties.get('updateTime')
            return properties
        except Exception as e:
            logger.error(f"Error getting forecast from {forecast_url}: {e}")
            self._fail(e)
            if getattr(getattr(e, 'response', None), 'status_code', None) == 404:
                # The forecast grid URL moved: forget the cached lookup so
                # the next cycle asks NWS for the new one.
                self._points_cache.clear()
            return None
    
    def get_marine_forecast(self, lat: float, lon: float) -> Optional[Dict]:
        """Get marine forecast for coastal areas"""
        try:
            marine_data = {}
            
            # Fetch PKZ766 from NOAA text product
            try:
                text_url = MARINE_URL
                response = self._get(text_url)
                response.raise_for_status()
                if response.status_code == 200:
                    text_content = response.text
                    
                    if 'PKZ766' not in text_content:
                        raise ValueError('PKZ766 section not found in the marine bulletin')

                    # Parse the text to find PKZ766 section
                    if 'PKZ766' in text_content:
                        # Extract the PKZ766 section
                        lines = text_content.split('\n')
                        pkz766_content = []
                        in_pkz766 = False
                        
                        for i, line in enumerate(lines):
                            if 'PKZ766' in line:
                                in_pkz766 = True
                                pkz766_content.append(line)
                                continue
                            
                            if in_pkz766:
                                # Stop at next zone or $$ marker
                                if line.startswith('PKZ') and 'PKZ766' not in line:
                                    break
                                if line.strip() == '$$':
                                    break
                                pkz766_content.append(line)
                        
                        if pkz766_content:
                            marine_data['PKZ766'] = {
                                'name': 'Pribilof Islands Nearshore Waters',
                                'raw_text': '\n'.join(pkz766_content),
                                'source': text_url
                            }
                            logger.info("Successfully fetched PKZ766 marine forecast")
            except Exception as e:
                logger.warning(f"Could not fetch PKZ766 text product: {e}")
                self._fail(e)
            
            return marine_data if marine_data else None
            
        except Exception as e:
            logger.error(f"Error getting marine forecast: {e}")
            return None
    
    def fetch_all_forecasts(self) -> Dict:
        """Fetch all forecasts for configured zip codes"""
        results = {}

        # One marine bulletin covers both islands, so fetch it once per
        # cycle instead of once per zip code.
        self.failures = {}
        self._context = 'marine'
        marine_forecast = self.get_marine_forecast(0, 0)

        for zip_code in self.zip_codes:
            logger.info(f"Fetching forecast for zip code: {zip_code}")
            self._context = zip_code
            
            coords = self.get_coordinates_from_zip(zip_code)
            if not coords:
                logger.warning(f"Could not get coordinates for {zip_code}")
                continue
            
            zip_data = {
                'zip_code': zip_code,
                'location': coords['city'],
                'coordinates': {'lat': coords['lat'], 'lon': coords['lon']},
                # Alaska time with its UTC offset (-09:00 AKST / -08:00 AKDT).
                # The old value was UTC with no offset, which browsers read
                # as the viewer's local time and showed hours off.
                'timestamp': local_now().isoformat(timespec='seconds'),
                'local_forecast': None,
                'marine_forecast': None
            }
            
            # Get forecast URLs
            forecast_urls = self.get_forecast_urls(coords['lat'], coords['lon'])
            if forecast_urls and forecast_urls['forecast']:
                # Get local forecast
                local_forecast = self.get_forecast(forecast_urls['forecast'])
                if local_forecast:
                    zip_data['local_forecast'] = {
                        'updated': local_forecast.get('updated'),
                        'periods': local_forecast.get('periods', [])[:7]  # Next 7 periods
                    }
                # Get hourly forecast
                if forecast_urls.get('forecast_hourly'):
                    hourly_forecast = self.get_forecast(forecast_urls['forecast_hourly'])
                    if hourly_forecast:
                        zip_data['hourly_forecast'] = {
                            'updated': hourly_forecast.get('updated'),
                            'periods': hourly_forecast.get('periods', [])[:24]  # Next 24 hours
                        }

            # Marine forecast (fetched once above)
            if marine_forecast:
                zip_data['marine_forecast'] = marine_forecast
            
            results[zip_code] = zip_data
            
            # Be nice to the API
            time.sleep(1)
        
        return results
    
    def format_output(self, data: Dict) -> str:
        """Format the forecast data for display"""
        output = []
        output.append("=" * 80)
        output.append(f"WEATHER FORECAST REPORT - {local_now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
        output.append("=" * 80)
        
        for zip_code, zip_data in data.items():
            output.append(f"\n{'='*80}")
            output.append(f"ZIP CODE: {zip_code} - {zip_data['location']}")
            output.append(f"Coordinates: {zip_data['coordinates']['lat']}, {zip_data['coordinates']['lon']}")
            output.append(f"{'='*80}")
            
            # Local Forecast
            if zip_data['local_forecast']:
                output.append(f"\n--- LOCAL FORECAST ---")
                output.append(f"Updated: {zip_data['local_forecast']['updated']}")
                for period in zip_data['local_forecast']['periods']:
                    output.append(f"\n{period['name']}:")
                    output.append(f"  Temperature: {period['temperature']}°{period['temperatureUnit']}")
                    output.append(f"  Wind: {period.get('windSpeed', 'N/A')} {period.get('windDirection', '')}")
                    output.append(f"  {period['detailedForecast']}")
            else:
                output.append(f"\n--- LOCAL FORECAST ---")
                output.append("No local forecast data available")
            
            # Marine Forecast
            if zip_data['marine_forecast']:
                output.append(f"\n--- MARINE FORECAST ---")
                for zone_id, zone_data in zip_data['marine_forecast'].items():
                    output.append(f"\nZone {zone_id}: {zone_data.get('name', 'Unknown')}")
                    if 'periods' in zone_data:
                        for period in zone_data['periods'][:3]:  # First 3 periods
                            output.append(f"  {period.get('name', 'N/A')}:")
                            output.append(f"    {period.get('detailedForecast', 'No details available')}")
            else:
                output.append(f"\n--- MARINE FORECAST ---")
                output.append("No marine forecast data available")
        
        output.append(f"\n{'='*80}\n")
        return "\n".join(output)


def main():
    """Main application entry point"""
    # Configuration
    zip_codes = os.getenv('ZIP_CODES', '99660,99591').split(',')
    update_interval = int(os.getenv('UPDATE_INTERVAL', '3600'))  # Default 1 hour
    
    logger.info(f"Starting Weather Forecast Application")
    logger.info(f"Monitoring zip codes: {', '.join(zip_codes)}")
    logger.info(f"Update interval: {update_interval} seconds")
    
    fetcher = WeatherForecastFetcher(zip_codes)
    monitor = ForecastMonitor()
    logger.info("Forecast health monitoring enabled")
    run_once = os.getenv('RUN_ONCE', '').lower() in ('1', 'true', 'yes')

    while True:
        try:
            logger.info("Fetching weather forecasts...")
            forecasts = fetcher.fetch_all_forecasts()

            # Keep the last good forecast when a fetch fails. Writing an
            # empty forecast would blank the pages; the old one keeps its
            # old 'timestamp', so readers can see (and warn) that it is stale.
            failed_local = set()
            for zip_code, zip_data in list(forecasts.items()):
                if zip_data.get('local_forecast'):
                    continue
                failed_local.add(zip_code)
                island_name = zip_data.get('location', zip_code).replace(' ', '_').lower()
                previous_file = os.path.join(DATA_DIR, f'{island_name}_{zip_code}.json')
                try:
                    with open(previous_file) as f:
                        previous = json.load(f)
                    if previous.get('local_forecast'):
                        # The marine part comes from a different server, so
                        # use this cycle's result for it, not the old one.
                        previous['marine_forecast'] = zip_data.get('marine_forecast')
                        forecasts[zip_code] = previous
                        logger.warning(
                            f"Local forecast fetch failed for {zip_code}; keeping the "
                            f"previous one from {previous.get('timestamp')}")
                except (OSError, ValueError):
                    pass  # no usable previous file; fall through with the empty one

            # Save combined forecast to file
            output_file = os.path.join(DATA_DIR, 'latest_forecast.json')
            write_json(output_file, forecasts)
            logger.info(f"Saved forecast data to {output_file}")

            # Save individual island forecasts
            marine_forecasts_combined = {}
            for zip_code, zip_data in forecasts.items():
                island_name = zip_data.get('location', zip_code).replace(' ', '_').lower()

                # Save individual JSON
                individual_json = os.path.join(DATA_DIR, f'{island_name}_{zip_code}.json')
                write_json(individual_json, zip_data)
                logger.info(f"Saved {zip_data.get('location')} data to {individual_json}")

                # Save individual formatted text
                individual_txt = os.path.join(DATA_DIR, f'{island_name}_{zip_code}.txt')
                individual_formatted = fetcher.format_output({zip_code: zip_data})
                atomic_write(individual_txt, individual_formatted)
                logger.info(f"Saved {zip_data.get('location')} formatted forecast to {individual_txt}")

                # Collect marine forecasts
                if zip_data.get('marine_forecast'):
                    for zone_id, zone_data in zip_data['marine_forecast'].items():
                        if zone_id not in marine_forecasts_combined:
                            marine_forecasts_combined[zone_id] = zone_data
            
            # Save separate marine forecast file
            if marine_forecasts_combined:
                marine_json = os.path.join(DATA_DIR, 'pribilof_island_waters.json')
                write_json(marine_json, marine_forecasts_combined)
                logger.info(f"Saved marine forecast data to {marine_json}")

                # Format marine forecast text
                marine_txt = os.path.join(DATA_DIR, 'pribilof_island_waters.txt')
                marine_output = []
                marine_output.append("=" * 80)
                marine_output.append(f"PRIBILOF ISLANDS MARINE FORECAST - {local_now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
                marine_output.append("=" * 80)
                marine_output.append("")
                
                for zone_id, zone_data in marine_forecasts_combined.items():
                    marine_output.append(f"Zone {zone_id}: {zone_data.get('name', 'Unknown')}")
                    marine_output.append("-" * 80)
                    
                    # Check for raw text format (from text products)
                    if 'raw_text' in zone_data:
                        marine_output.append(zone_data['raw_text'])
                    # Check for structured periods format
                    elif 'periods' in zone_data and zone_data['periods']:
                        for period in zone_data['periods']:
                            marine_output.append(f"\n{period.get('name', 'N/A')}:")
                            marine_output.append(f"  {period.get('detailedForecast', 'No details available')}")
                    else:
                        marine_output.append("  No detailed forecast data available")
                    marine_output.append("")
                
                marine_output.append("=" * 80)
                
                atomic_write(marine_txt, "\n".join(marine_output))
                logger.info(f"Saved marine forecast text to {marine_txt}")

            # Save combined formatted output. (The full text used to be
            # printed to the container log every hour as well; it is in
            # latest_forecast.txt, so the log now gets one line instead.)
            formatted = fetcher.format_output(forecasts)
            text_output_file = os.path.join(DATA_DIR, 'latest_forecast.txt')
            atomic_write(text_output_file, formatted)
            logger.info(f"Saved combined formatted forecast to {text_output_file}")

            # Record successful attempts for each location
            for zip_code, zip_data in forecasts.items():
                # Record local forecast attempt (a kept previous forecast
                # still counts as a failed fetch)
                if zip_data.get('local_forecast') and zip_code not in failed_local:
                    forecast_time = zip_data['local_forecast'].get('updated')
                    monitor.record_attempt(
                        location=zip_code,
                        forecast_type='local',
                        success=True,
                        forecast_time=forecast_time
                    )
                else:
                    cause, detail = fetcher.failures.get(zip_code, (None, None))
                    monitor.record_attempt(
                        location=zip_code,
                        forecast_type='local',
                        success=False,
                        error_message=detail or "No local forecast data available",
                        cause=cause
                    )
                
            # Record the marine forecast attempt once per cycle, under the
            # zone id for both success and failure. (Failures used to be
            # filed under '<zip>_marine' while successes went to 'PKZ766',
            # so an outage could never be marked as over.)
            if marine_forecasts_combined:
                for zone_id in marine_forecasts_combined:
                    monitor.record_attempt(
                        location=zone_id,
                        forecast_type='marine',
                        success=True
                    )
            else:
                cause, detail = fetcher.failures.get('marine', (None, None))
                monitor.record_attempt(
                    location='PKZ766',
                    forecast_type='marine',
                    success=False,
                    error_message=detail or "No marine forecast data available",
                    cause=cause
                )

            # Show alerts if any
            alerts = monitor.get_alert_summary()
            if alerts:
                logger.warning("FORECAST ALERTS:")
                for alert in alerts:
                    logger.warning(f"  {alert}")

            # Push only what the monitor says is worth a push: one message
            # when an outage is confirmed, one when it ends.
            problems, recoveries = monitor.take_notifications()
            for line in problems + recoveries:
                logger.info(f"NOTIFY: {line}")
            notify_ntfy("Weather forecast alert", problems)
            notify_ntfy("Weather forecast recovered", recoveries,
                        priority='default', tags='white_check_mark')
            
            # Generate status report
            monitor.save_report()

            if run_once:
                logger.info("RUN_ONCE set, exiting after one cycle")
                break

            logger.info(f"Waiting {update_interval} seconds until next update...")
            time.sleep(update_interval)
            
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            time.sleep(60)  # Wait a minute before retrying


if __name__ == "__main__":
    main()
