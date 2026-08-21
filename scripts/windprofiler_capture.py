# -*- coding: utf-8 -*-
# scripts/windprofiler_capture.py
# 気象庁 ウィンドプロファイラ 全33地点を撮影し、地点ごとのraw画像をR2へ個別保存する。
# Discordへは投稿しない（前日分は windprofiler_daily_stations.py が1日1回まとめて配信する）。

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.windprofiler import main

if __name__ == "__main__":
    raise SystemExit(main())
