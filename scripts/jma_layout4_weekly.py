# -*- coding: utf-8 -*-

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# scripts/jma_layout4_weekly.py
# 週間4列結合専用。SKAISETU等はWCN（Weathercaster.jp）経由。
from module.jobs.weather_map import main_layout4

if __name__ == "__main__":
    main_layout4()
