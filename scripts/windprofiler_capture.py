# -*- coding: utf-8 -*-
# scripts/windprofiler_discord.py
# 気象庁 ウィンドプロファイラ 全33地点 → Discord (jma-windprofiler専用チャンネル)

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.windprofiler import main

if __name__ == "__main__":
    raise SystemExit(main())
