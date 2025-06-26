import urllib.request
from bs4 import BeautifulSoup

def find_latest_msm_file(date, pattern, fh):
    y, m, d = date.strftime("%Y"), date.strftime("%m"), date.strftime("%d")
    url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/{y}/{m}/{d}/"
    try:
        with urllib.request.urlopen(url) as res:
            soup = BeautifulSoup(res.read(), "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if pattern in href and fh in href and href.endswith("grib2.bin"):
                    print(f"[FOUND] {href}")
                    return f"{url}{href}"
    except Exception as e:
        print(f"[WARN] index.html取得失敗: {url} ({e})")
    return None

# 使い方例
from datetime import datetime
date = datetime(2025, 6, 22)
url = find_latest_msm_file(date, "MSM_GPV_Rjp_Lsurf", "FH00-15")
if url:
    print("[OK]", url)
    # urllib.request.urlretrieve(url, "保存先パス")
else:
    print("ファイルが見つかりません")
