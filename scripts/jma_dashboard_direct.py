# -*- coding: utf-8 -*-

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# scripts/jma_dashboard_direct.py
# 全部入り（気象庁直接取得版）専用。WCN（Weathercaster.jp）は経由しない。
from module.jobs.weather_map import main_dashboard_jma

if __name__ == "__main__":
    main_dashboard_jma()
