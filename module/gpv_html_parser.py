# module/utils/gpv_html_parser.py
# ===============================================
# サーバindex.htmlをパースしてMSM秋田局地L-pall/Lsurf実在ペアを抽出
# ===============================================

import requests
from bs4 import BeautifulSoup
import re

def find_existing_msm_pairs(base_url, ymd):
    """
    指定日ディレクトリのindex.htmlから
    MSM秋田局地のL-pall/Lsurfファイルで揃っている（init/FH帯完全一致）ペアを返す
    Returns: [(l_pall_url, lsurf_url, init_dt, fh_band), ...]
    """
    url = f"{base_url}/{ymd[:4]}/{ymd[4:6]}/{ymd[6:8]}/"
    res = requests.get(url)
    soup = BeautifulSoup(res.text, "html.parser")
    files = [a.text for a in soup.find_all('a')]
    # パターンマッチ
    patt = re.compile(r"Z__C_RJTD_(\d{10})00_MSM_GPV_Rjp_L-(pall|surf)_FH(\d{2}-\d{2})_grib2\.bin")
    meta = []
    for f in files:
        m = patt.match(f)
        if m:
            init_str, ltype, fh_band = m.groups()
            meta.append((init_str, ltype, fh_band, f))
    # (init, fh_band)ごとに両方あるペアだけ
    from collections import defaultdict
    temp = defaultdict(dict)
    for init, ltype, fh, fname in meta:
        temp[(init, fh)][ltype] = fname
    # 完全ペアだけリスト化
    pairs = []
    for (init, fh), v in temp.items():
        if "pall" in v and "surf" in v:
            pairs.append((
                url + v["pall"], url + v["surf"],
                init, fh
            ))
    return pairs
