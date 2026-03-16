#!/usr/bin/env python3
import sys, os, time

HEARTBEAT = os.getenv("HEARTBEAT_PATH", "/app/data/heartbeat")
MAX_AGE   = 120

if not os.path.exists(HEARTBEAT):
    sys.exit(1)

age = time.time() - os.path.getmtime(HEARTBEAT)
sys.exit(0 if age < MAX_AGE else 1)
