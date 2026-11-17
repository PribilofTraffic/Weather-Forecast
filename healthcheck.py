#!/usr/bin/env python3
"""
Container health check for weather-forecast.

Healthy means the output is fresh: latest_forecast.json was rewritten within
two update intervals plus ten minutes of slack. A process that is still
running but has stopped producing output shows up as unhealthy.

Inputs (environment): DATA_DIR (default /data), UPDATE_INTERVAL seconds
(default 3600). Exit code 0 = healthy, 1 = unhealthy.
"""

import os
import sys
import time

DATA_DIR = os.getenv('DATA_DIR', '/data')
UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', '3600'))
TARGET = os.path.join(DATA_DIR, 'latest_forecast.json')
MAX_AGE = 2 * UPDATE_INTERVAL + 600

try:
    age = time.time() - os.path.getmtime(TARGET)
except OSError as e:
    print(f"unhealthy: {e}")
    sys.exit(1)

if age > MAX_AGE:
    print(f"unhealthy: {TARGET} is {int(age)}s old (limit {MAX_AGE}s)")
    sys.exit(1)

print(f"healthy: {TARGET} is {int(age)}s old")
