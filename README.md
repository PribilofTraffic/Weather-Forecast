# Weather Forecast Collector

A small Docker service that fetches National Weather Service forecasts on a schedule and saves them as JSON and plain-text files, ready for a website, a dashboard or a script to read.

It was built for the Pribilof Islands, St. Paul and St. George, two small islands in the Bering Sea off Alaska, where the weather decides whether planes land and boats go out. It feeds the forecast pages on [pribiloftraffic.com](https://www.pribiloftraffic.com). It works for any place the US National Weather Service covers: give it a zip code or a pair of coordinates.

## What it does

- Fetches the 7-period forecast and the next 24 hours, hour by hour, for each place you list.
- Optionally fetches the marine forecast for a coastal zone.
- Writes one JSON file and one text file per place, plus a combined file.
- Keeps the last good forecast if a fetch fails, so readers never get an empty file.
- Works out why a fetch failed: your internet, the weather service, or a bug here.
- Can push an alert to [ntfy](https://ntfy.sh) when a source stays down.

No API key is needed. Forecasts come from [api.weather.gov](https://www.weather.gov/documentation/services-web-api).

## Quick start

You need Docker with the Compose plugin.

```bash
git clone https://github.com/PribilofTraffic/Weather-Forecast.git
cd Weather-Forecast
cp docker-compose.example.yml docker-compose.yml
```

Open `docker-compose.yml`, set your time zone and your zip codes, then start it:

```bash
docker compose up -d
```

Within a few seconds the forecast files appear in `./data`:

```bash
cat data/latest_forecast.txt
```

## Updating

```bash
git pull
docker compose up -d --build
```

Pulling an update does not touch your settings or your data. Your `docker-compose.yml`, any `.env` file and the whole `data/` folder (forecasts, health history, remembered zip codes) are ignored by Git, so they stay exactly as you left them. New settings are added with defaults that keep existing setups working; check `docker-compose.example.yml` after an update to see what is new.

## Choosing places

Use either setting, or both.

| Setting | Format | Example |
|---|---|---|
| `ZIP_CODES` | US zip codes, comma-separated | `99501,99701` |
| `LOCATIONS` | `Name,latitude,longitude`, separated by `;` | `Cabin,61.52,-149.63;Boat Harbor,60.12,-149.44` |

Each zip code is turned into coordinates once, through the free [Zippopotam.us](https://www.zippopotam.us) lookup, and remembered in `data/zip_cache.json`. `LOCATIONS` entries involve no lookup service; use them for a place a zip code does not describe well, or if you would rather not send a zip code to a third party.

With neither set, the two Pribilof Islands zip codes (`99660`, `99591`) are used. Those two are built in and need no lookup.

Coordinates over open water or outside the United States have no NWS forecast. The log says so plainly when that happens.

## Marine forecast (optional)

NWS publishes coastal marine forecasts as text bulletins, each covering several zones. To collect one, set the zone id and the bulletin that contains it:

```yaml
- MARINE_ZONE=PKZ766
- MARINE_URL=https://tgftp.nws.noaa.gov/data/raw/fz/fzak52.pafc.cwf.alu.txt
- MARINE_ZONE_NAME=Pribilof Islands Nearshore Waters
```

Find your zone and its bulletin at [weather.gov/marine](https://www.weather.gov/marine/). The marine forecast is off unless `MARINE_ZONE` is set. The one exception is the built-in Pribilof setup, where it defaults to zone `PKZ766`; set `MARINE_ZONE=` (empty) to turn it off there.

## Output files

Everything is written to the `data/` folder.

| File | Contents |
|---|---|
| `latest_forecast.json`, `latest_forecast.txt` | every place combined |
| `<name>_<zip>.json`, `.txt` | one place given by zip code, for example `anchorage_99501.json` |
| `<name>.json`, `.txt` | one place given in `LOCATIONS`, for example `cabin.json` |
| `marine_<zone>.json`, `.txt` | the marine forecast, for example `marine_pkz766.json` (the built-in Pribilof setup names it `pribilof_island_waters`) |
| `forecast_health.json`, `forecast_report.txt` | fetch history, outages and their causes |
| `zip_cache.json` | remembered zip code lookups |

Each place's JSON looks like this:

```json
{
  "zip_code": "99501",
  "location": "Anchorage",
  "coordinates": {"lat": 61.2116, "lon": -149.8761},
  "timestamp": "2026-11-16T18:16:46-09:00",
  "local_forecast": {"updated": "...", "periods": [ ... 7 periods ... ]},
  "hourly_forecast": {"updated": "...", "periods": [ ... 24 hours ... ]},
  "marine_forecast": null
}
```

The periods are passed through from NWS unchanged (`name`, `temperature`, `windSpeed`, `shortForecast`, `detailedForecast` and so on).

`timestamp` is when the forecast was fetched, in your time zone with its UTC offset. Because the zone is a named one (`TZ`), the switch between standard and daylight time happens on its own.

## When something goes wrong

Each failed fetch is sorted into one of four causes and recorded in `forecast_health.json`, `forecast_report.txt` and the container log.

| Cause | Meaning | Alert |
|---|---|---|
| `local_network` | your own internet or DNS is down | none while it lasts; one summary when it returns |
| `source_down` | NWS is not answering, or returns a server error | one after three failed cycles, one on recovery |
| `source_stale` | NWS answers, but the forecast is more than a day old | same |
| `our_error` | NWS answered and the service could not use it: format changed, URL gone, request refused | at once |

Alerts are only sent if `NTFY_URL` and `NTFY_TOPIC` are set.

`docker ps` shows the container as unhealthy if `latest_forecast.json` has not been rewritten within two update intervals plus ten minutes.

```bash
cat data/forecast_report.txt     # status, uptime and recent outages per place
docker compose logs -f           # live log
```

## Settings

All settings are environment variables in `docker-compose.yml`.

| Setting | Default | Purpose |
|---|---|---|
| `TZ` | `America/Anchorage` | time zone for every time written |
| `ZIP_CODES` | `99660,99591` if `LOCATIONS` is also unset | zip codes to fetch |
| `LOCATIONS` | none | named coordinates to fetch |
| `UPDATE_INTERVAL` | `3600` | seconds between fetches; NWS refreshes about hourly, so shorter gains nothing |
| `MARINE_ZONE`, `MARINE_URL`, `MARINE_ZONE_NAME`, `MARINE_FILE` | off | marine forecast, see above |
| `USER_AGENT` | `weather-forecast-collector/1.1` | how the service identifies itself to NWS, which asks for an app name and a contact |
| `NTFY_URL`, `NTFY_TOPIC`, `NTFY_TOKEN` | none | where alerts are pushed |
| `ALERT_AFTER_FAILURES` | `3` | failed cycles before a source-side alert |
| `STALE_FORECAST_HOURS` | `24` | age at which a forecast counts as stale |
| `FETCH_RETRIES` | `3` | tries per request |
| `ZIP_LOOKUP_URL` | Zippopotam.us | zip code lookup service; `{zip}` is replaced by the zip code |
| `CONNECTIVITY_PROBES` | `1.1.1.1:443,8.8.8.8:53` | hosts tried with a bare TCP connection to tell whether your own internet is up |
| `RUN_ONCE` | off | `1` runs a single cycle and exits, handy for testing |

## How it is polite to the weather service

- One fetch an hour by default, matching how often NWS refreshes the forecast.
- The lookup of which forecast grid a place falls in is cached for a day, as NWS's own cache headers ask.
- Requests time out after 15 seconds and are retried a few times with a pause between tries.
- Every request carries a User-Agent that says who is asking.

## Files in this repo

| File | Purpose |
|---|---|
| `app.py` | the fetch loop and file writing |
| `monitor.py` | health tracking, the status report and the alert rules |
| `diagnose.py` | works out whose end a failure is on |
| `healthcheck.py` | the container health check |
| `Dockerfile`, `requirements.txt` | the image |
| `docker-compose.example.yml` | a starting point for your own compose file |
| `sync_to_web.sh`, `view_status.sh` | optional helper scripts |
| `BUILD_LOG.md` | notes on how and why it was built |

## Using the files from a website

A web server or another script can read the files straight from `data/`. Each file is written to a temporary name and then renamed, so a reader never sees a half-written file. If something reads these files, do not move `data/` or rename the outputs without updating it.
