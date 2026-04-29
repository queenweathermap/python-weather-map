# -*- coding: utf-8 -*-

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# scripts/jma_weather_map.py
from module.jobs.weather_map import main

if __name__ == "__main__":
    main()
