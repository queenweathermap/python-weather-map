# -*- coding: utf-8 -*-
# WCN暫定公開の申込(Notion)→購読者DB(Status=wcn)。詳しくは module/jobs/wcn_signup.py。
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module.jobs.wcn_signup import main

if __name__ == "__main__":
    main()
