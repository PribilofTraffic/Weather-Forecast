#!/usr/bin/env python3
"""
Weather Forecast Health Monitor

Monitors API availability, data freshness, and generates status reports.
Ensures no stale or fake forecasts are served.
"""

import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from pathlib import Path

import diagnose


DATA_DIR = os.getenv("DATA_DIR", "/data")
MONITOR_FILE = os.path.join(DATA_DIR, "forecast_health.json")
REPORT_FILE = os.path.join(DATA_DIR, "forecast_report.txt")

# A forecast whose NWS issue time is older than this is called stale.
STALE_FORECAST_HOURS = float(os.getenv("STALE_FORECAST_HOURS", "24"))
# A location nobody has tried to fetch for this long is retired: it stays in
# the health file as history but no longer raises alerts.
RETIRED_AFTER_HOURS = float(os.getenv("RETIRED_AFTER_HOURS", "24"))
# How many cycles in a row a problem on the source's end (not answering, or
# not updating) must last before one alert is pushed. A fault on our side
# that needs a fix is pushed at once; our own internet being down is never
# pushed while it lasts (the push could not get out) and is summarised when
# the link comes back.
ALERT_AFTER_FAILURES = int(os.getenv("ALERT_AFTER_FAILURES", "3"))


def _atomic_write(path: str, text: str) -> None:
    """Write to a temp file then rename, so readers never see a partial file."""
    tmp = f"{path}.tmp"
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


class ForecastMonitor:
    """Monitor forecast API health and data freshness."""
    
    def __init__(self):
        """Initialize the monitor."""
        self.health_data = self._load_health_data()
        # Messages waiting to be pushed; collected by take_notifications().
        self._problems: List[str] = []
        self._recoveries: List[str] = []

    def take_notifications(self):
        """Return (problems, recoveries) queued since the last call."""
        problems, recoveries = self._problems, self._recoveries
        self._problems, self._recoveries = [], []
        return problems, recoveries
        
    def _load_health_data(self) -> Dict:
        """Load existing health data or create new."""
        if os.path.exists(MONITOR_FILE):
            try:
                with open(MONITOR_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        
        return {
            "locations": {},
            "last_updated": None
        }
    
    def _save_health_data(self) -> None:
        """Save health data to file."""
        try:
            _atomic_write(MONITOR_FILE, json.dumps(self.health_data, indent=2))
        except Exception as e:
            print(f"Error saving health data: {e}")

    def _is_retired(self, loc: Dict) -> bool:
        """True if this location has not been attempted recently.

        Covers keys left behind by old naming schemes (for example
        '99660_marine'), which would otherwise report an outage forever.
        """
        last_attempt = loc.get("last_attempt") or loc.get("last_failure") or loc.get("last_success")
        if not last_attempt:
            return True
        try:
            age = datetime.utcnow() - datetime.fromisoformat(last_attempt)
        except ValueError:
            return True
        return age > timedelta(hours=RETIRED_AFTER_HOURS)
    
    def record_attempt(
        self,
        location: str,
        forecast_type: str,
        success: bool,
        forecast_time: Optional[str] = None,
        error_message: Optional[str] = None,
        cause: Optional[str] = None
    ) -> None:
        """
        Record a forecast fetch attempt.
        
        Args:
            location: Location identifier (zip code or zone)
            forecast_type: Type of forecast (local, marine)
            success: Whether fetch succeeded
            forecast_time: Timestamp from forecast data
            error_message: Error message if failed
            cause: Whose end a failure is on (see diagnose.py); None if unknown
        """
        now = datetime.utcnow().isoformat()
        
        if location not in self.health_data["locations"]:
            self.health_data["locations"][location] = {
                "first_seen": now,
                "total_attempts": 0,
                "successful_attempts": 0,
                "failed_attempts": 0,
                "last_success": None,
                "last_failure": None,
                "current_outage_start": None,
                "outage_history": [],
                "last_forecast_time": None,
                "stale_forecast_count": 0
            }
        
        loc = self.health_data["locations"][location]
        loc["total_attempts"] += 1
        loc["last_attempt"] = now
        
        if success:
            loc["successful_attempts"] += 1
            loc["last_success"] = now
            
            # Check if forecast is fresh
            if forecast_time:
                loc["last_forecast_time"] = forecast_time
                
                # Check if the forecast NWS handed us is an old one. Both
                # times are compared as zone-aware values (the old code
                # mixed aware and naive times, which raised and was
                # silently ignored, so this check never ran).
                try:
                    forecast_dt = datetime.fromisoformat(forecast_time.replace('Z', '+00:00'))
                    if forecast_dt.tzinfo is None:
                        forecast_dt = forecast_dt.replace(tzinfo=timezone.utc)
                    age_hours = (datetime.now(timezone.utc) - forecast_dt).total_seconds() / 3600

                    was_stale = loc.get("forecast_stale", False)
                    loc["forecast_stale"] = age_hours > STALE_FORECAST_HOURS
                    if loc["forecast_stale"]:
                        loc["stale_forecast_count"] += 1
                        loc["last_stale_warning"] = now
                        loc["stale_cycles"] = loc.get("stale_cycles", 0) + 1
                        if loc["stale_cycles"] == ALERT_AFTER_FAILURES:
                            loc["stale_alert_sent"] = True
                            self._problems.append(
                                f"{location}: forecast is {age_hours:.0f} hours old - "
                                + diagnose.describe(diagnose.SOURCE_STALE))
                    else:
                        if was_stale and loc.get("stale_alert_sent"):
                            self._recoveries.append(f"{location}: forecast is being updated again")
                        loc["stale_cycles"] = 0
                        loc["stale_alert_sent"] = False
                except Exception:
                    pass
            
            # If recovering from outage, record it
            if loc["current_outage_start"]:
                outage_duration = self._calculate_duration(
                    loc["current_outage_start"],
                    now
                )
                loc["outage_history"].append({
                    "start": loc["current_outage_start"],
                    "end": now,
                    "duration_minutes": outage_duration,
                    "cause": loc.get("current_cause")
                })
                # Say it is over if we said it had started, or if it was
                # our own link and lasted long enough to be worth knowing.
                was_local = loc.get("current_cause") == diagnose.LOCAL_NETWORK
                long_enough = loc.get("consecutive_failures", 0) >= ALERT_AFTER_FAILURES
                if loc.get("alert_sent") or (was_local and long_enough):
                    self._recoveries.append(
                        f"{location}: back after {outage_duration} minutes - was: "
                        + diagnose.describe(loc.get("current_cause")))
                loc["current_outage_start"] = None
            loc["consecutive_failures"] = 0
            loc["current_cause"] = None
            loc["alert_sent"] = False
        else:
            loc["failed_attempts"] += 1
            loc["last_failure"] = now
            loc["last_error"] = error_message
            
            # Mark start of outage if this is first failure
            if not loc["current_outage_start"]:
                loc["current_outage_start"] = now

            loc["consecutive_failures"] = loc.get("consecutive_failures", 0) + 1
            loc["current_cause"] = cause

            # Decide whether this failure is worth a push (once per outage).
            if not loc.get("alert_sent"):
                if cause == diagnose.LOCAL_NETWORK:
                    push = False  # cannot get out; summarised on recovery
                elif cause == diagnose.OUR_ERROR:
                    push = True   # ours to fix: say so straight away
                else:
                    push = loc["consecutive_failures"] >= ALERT_AFTER_FAILURES
                if push:
                    loc["alert_sent"] = True
                    self._problems.append(
                        f"{location}: no {forecast_type} forecast for "
                        f"{loc['consecutive_failures']} cycle(s) - "
                        + diagnose.describe(cause, error_message))
        
        self.health_data["last_updated"] = now
        self._save_health_data()
    
    def _calculate_duration(self, start_iso: str, end_iso: str) -> int:
        """Calculate duration in minutes between two ISO timestamps."""
        try:
            start = datetime.fromisoformat(start_iso)
            end = datetime.fromisoformat(end_iso)
            return int((end - start).total_seconds() / 60)
        except Exception:
            return 0
    
    def get_location_status(self, location: str) -> Dict:
        """
        Get current status of a location.
        
        Args:
            location: Location identifier
            
        Returns:
            Dictionary with status information
        """
        if location not in self.health_data["locations"]:
            return {
                "status": "unknown",
                "message": "No forecast attempts recorded"
            }
        
        loc = self.health_data["locations"][location]
        
        # Check if currently in outage
        if loc["current_outage_start"]:
            outage_duration = self._calculate_duration(
                loc["current_outage_start"],
                datetime.utcnow().isoformat()
            )
            return {
                "status": "offline",
                "message": f"no data for {outage_duration} minutes - "
                           + diagnose.describe(loc.get("current_cause")),
                "outage_start": loc["current_outage_start"],
                "cause": loc.get("current_cause"),
                "last_error": loc.get("last_error", "Unknown error")
            }
        
        # Check last success time
        if loc["last_success"]:
            last_success = datetime.fromisoformat(loc["last_success"])
            time_since = datetime.utcnow() - last_success
            
            if time_since < timedelta(hours=2):
                # Warn only while the latest forecast is stale, not forever
                # after the first stale one.
                if loc.get("forecast_stale"):
                    return {
                        "status": "warning",
                        "message": "forecast is old - " + diagnose.describe(diagnose.SOURCE_STALE),
                        "cause": diagnose.SOURCE_STALE,
                        "last_success": loc["last_success"]
                    }
                
                return {
                    "status": "online",
                    "message": "API operating normally",
                    "last_success": loc["last_success"],
                    "last_forecast_time": loc.get("last_forecast_time")
                }
            else:
                return {
                    "status": "stale",
                    "message": f"No fresh data for {int(time_since.total_seconds() / 3600)} hours",
                    "last_success": loc["last_success"]
                }
        
        return {
            "status": "unknown",
            "message": "No successful fetches yet"
        }
    
    def get_uptime_percentage(self, location: str) -> float:
        """Calculate uptime percentage for a location."""
        if location not in self.health_data["locations"]:
            return 0.0
        
        loc = self.health_data["locations"][location]
        total = loc["total_attempts"]
        
        if total == 0:
            return 0.0
        
        return (loc["successful_attempts"] / total) * 100
    
    def get_alert_summary(self) -> List[str]:
        """
        Get list of current alerts.
        
        Returns:
            List of alert messages
        """
        alerts = []
        
        for location, loc in self.health_data["locations"].items():
            if self._is_retired(loc):
                continue
            status = self.get_location_status(location)

            if status["status"] == "offline":
                alerts.append(f"🔴 {location}: {status['message']}")
            elif status["status"] == "warning":
                alerts.append(f"⚠️  {location}: {status['message']}")
            elif status["status"] == "stale":
                alerts.append(f"🟡 {location}: {status['message']}")
        
        return alerts
    
    def generate_report(self) -> str:
        """
        Generate a human-readable status report.
        
        Returns:
            Formatted status report string
        """
        now = datetime.utcnow()
        lines = []
        
        lines.append("=" * 70)
        lines.append("WEATHER FORECAST API HEALTH REPORT")
        lines.append(f"Generated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append("=" * 70)
        
        if not self.health_data["locations"]:
            lines.append("\nNo forecast data collected yet.")
            return "\n".join(lines)
        
        # Overall summary
        total_locations = len(self.health_data["locations"])
        online_count = sum(1 for loc in self.health_data["locations"].values() 
                          if not loc.get("current_outage_start"))
        
        lines.append(f"\nOVERALL STATUS")
        lines.append(f"  Total Locations: {total_locations}")
        lines.append(f"  Online: {online_count}")
        lines.append(f"  Offline: {total_locations - online_count}")
        
        # Per-location details
        lines.append(f"\nLOCATION DETAILS")
        lines.append("-" * 70)
        
        for location in sorted(self.health_data["locations"].keys()):
            loc = self.health_data["locations"][location]
            status = self.get_location_status(location)
            uptime = self.get_uptime_percentage(location)
            
            lines.append(f"\n📍 Location: {location}")
            lines.append(f"   Status: {status['status'].upper()} - {status['message']}")
            lines.append(f"   Uptime: {uptime:.1f}%")
            lines.append(f"   Total Attempts: {loc['total_attempts']}")
            lines.append(f"   Successful: {loc['successful_attempts']}")
            lines.append(f"   Failed: {loc['failed_attempts']}")
            
            if loc.get("last_forecast_time"):
                lines.append(f"   Last Forecast Time: {loc['last_forecast_time']}")
            
            if loc.get("stale_forecast_count", 0) > 0:
                lines.append(f"   ⚠️  Stale Forecasts Detected: {loc['stale_forecast_count']}")
            
            if loc.get("last_success"):
                last_success = datetime.fromisoformat(loc["last_success"])
                time_since = datetime.utcnow() - last_success
                lines.append(f"   Last Success: {int(time_since.total_seconds() / 60)} minutes ago")
            
            if loc.get("current_outage_start"):
                outage_start = datetime.fromisoformat(loc["current_outage_start"])
                outage_duration = datetime.utcnow() - outage_start
                lines.append(f"   🔴 Current Outage: {int(outage_duration.total_seconds() / 60)} minutes")
                if loc.get("last_error"):
                    lines.append(f"   Last Error: {loc['last_error']}")
            
            # Outage history
            if loc.get("outage_history"):
                recent_outages = loc["outage_history"][-3:]  # Last 3 outages
                if recent_outages:
                    lines.append(f"   Recent Outages:")
                    for outage in recent_outages:
                        lines.append(f"     - {outage['duration_minutes']} minutes "
                                   f"(ended {outage['end']})"
                                   + (f" [{outage['cause']}]" if outage.get('cause') else ""))
        
        lines.append("\n" + "=" * 70)
        
        # Alerts
        alerts = self.get_alert_summary()
        if alerts:
            lines.append("\n🚨 ACTIVE ALERTS:")
            for alert in alerts:
                lines.append(f"  {alert}")
            lines.append("")
        
        return "\n".join(lines)
    
    def save_report(self) -> None:
        """Generate and save status report to file."""
        try:
            _atomic_write(REPORT_FILE, self.generate_report())
        except Exception as e:
            print(f"Error saving report: {e}")
    
    def check_data_freshness(self, forecast_data: Dict) -> bool:
        """
        Check if forecast data is fresh (not stale).
        
        Args:
            forecast_data: Forecast data dictionary
            
        Returns:
            True if data is fresh, False if stale
        """
        try:
            # Check if forecast has a timestamp
            if 'updated' in forecast_data:
                updated_time = datetime.fromisoformat(
                    forecast_data['updated'].replace('Z', '+00:00')
                )
                now = datetime.utcnow()
                age_hours = (now - updated_time).total_seconds() / 3600
                
                # Forecast is stale if older than 12 hours
                return age_hours <= 12
            
            return True  # Assume fresh if no timestamp
        except Exception:
            return True  # Assume fresh if can't parse
