# module/utils/gpv_html_parser.py
# ===============================================
# サーバindex.htmlをパースしてMSM秋田局地L-pall/Lsurfファイル実在リスト抽出
# ===============================================

import requests
from bs4 import BeautifulSoup
import re
from collections import defaultdict

def find_existing_msm_files(base_url, ymd):
    """
    指定日ディレクトリのindex.htmlから
    MSM秋田局地L-pall/Lsurfファイルをinit/FH帯ごとに抽出
    Returns: [
      {"init": ..., "fh": ..., "l_pall_url": ..., "lsurf_url": ...}, ...
    ]
    ※ どちらか一方しかない場合も None で返す
    """
    url = f"{base_url}/{ymd[:4]}/{ymd[4:6]}/{ymd[6:8]}/"
    res = requests.get(url)
    soup = BeautifulSoup(res.text, "html.parser")
    files = [a.text for a in soup.find_all('a')]

    patt = re.compile(r"Z__C_RJTD_(\d{10})00_MSM_GPV_Rjp_L-(pall|surf)_FH(\d{2}-\d{2})_grib2\.bin")
    # {(init, fh): {"pall":..., "surf":...}}
    file_dict = defaultdict(dict)
    for f in files:
        m = patt.match(f)
        if m:
            init_str, ltype, fh_band = m.groups()
            file_dict[(init_str, fh_band)][ltype] = url + f

    # どちらか一方しかないものも含めてリスト化
    result = []
    for (init, fh), v in file_dict.items():
        result.append({
            "init": init,
            "fh": fh,
            "l_pall_url": v.get("pall"),
            "lsurf_url": v.get("surf"),
        })
    return result
