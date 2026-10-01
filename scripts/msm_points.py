# -*- coding: utf-8 -*-
# =============================================================================
# scripts/msm_points.py
#
# MSM数値予報の格子点値を、アメダス地点ごと・地域別のJSONにしてR2へ置く
# (会員向けPWAの「MSM 数値予報」の表が読む)。詳しくは module/jobs/msm_points.py。
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from module.jobs.msm_points import main


if __name__ == "__main__":
    main()
