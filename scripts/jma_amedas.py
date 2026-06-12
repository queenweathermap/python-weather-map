# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_amedas.py
#
# ランナー: 本体 module/jobs/amedas.py を実行するだけ。
# （guidance / weather_map と同じ構成）
# =============================================================================

import os
import sys

# リポジトリ直下を import パスに通す（module パッケージを解決するため）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.jobs.amedas import main


if __name__ == "__main__":
    main()
