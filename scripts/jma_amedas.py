# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_amedas.py
#
# アメダス観測値・ランキング(JMA公開API) → R2 → Discord(#177-amedas)
# → Notion。
#
# 鷹巣・秋田・横手のJMAアメダス3地点詳細(module.jobs.amedas.main())は
# 2026-09-18よりmodule/jobs/weather_warning.py(秋田 注意報警報等＋アメダス
# 詳細ジョブ、jma-warningチャンネル)に一本化した。従来はこのジョブと
# weather_warning.py側の両方で同じ3地点詳細を別々に取得・R2保存しており
# 二重化していたため。
# =============================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.amedas import main_ranking


if __name__ == "__main__":
    main_ranking(post_notion=True)
