#!/bin/bash
cd /root/.openclaw/workspace
python3 browser_monitor.py 2>&1 | tail -10
