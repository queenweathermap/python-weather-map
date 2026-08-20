# -*- coding: utf-8 -*-
# scripts/windprofiler_daily_stations.py
# ウィンドプロファイラ 1日まとめ（地点別、自分用Discordチャンネルへ通常投稿）

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.windprofiler import main_daily_stations

if __name__ == "__main__":
    raise SystemExit(main_daily_stations())
