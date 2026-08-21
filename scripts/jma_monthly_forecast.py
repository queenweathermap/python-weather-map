# -*- coding: utf-8 -*-

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# scripts/jma_monthly_forecast.py
# 1か月予報資料専用（気象庁直接取得版）。WCN（Weathercaster.jp）は経由しない。
from module.jobs.weather_map import main_monthly

if __name__ == "__main__":
    main_monthly()
