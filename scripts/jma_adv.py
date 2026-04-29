# -*- coding: utf-8 -*-

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# scripts/jma_adv.py
from module.jobs.adv_tgv import main


if __name__ == "__main__":
    main()
