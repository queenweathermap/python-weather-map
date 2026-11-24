"""気象庁「過去の気象データ検索(高層)」の指定気圧面データを取得し、
stuve_grid が使う levels 形式へ変換する。

hourly_usp.php の hour は日本時間の 9/21(=00Z/12Z)。表は地上1行+指定気圧面25行。
相対湿度からMagnus式で露点を出す。風速はm/s(unit="m/s")。
"""
import math
import re
import time
import urllib.request

URL = ("https://www.data.jma.go.jp/stats/etrn/upper/view/hourly_usp.php"
       "?year={y}&month={m}&day={d}&hour={h}&atm=&point={p}&view=")
UA = "Mozilla/5.0 (compatible; weather-chart/1.0)"
ROW = re.compile(r'<tr class="mtx" style="text-align:right;">(.*?)</tr>', re.S)
CELL = re.compile(r"<td[^>]*>([^<]*)</td>")


def _num(s):
    s = s.strip()
    if not s or "/" in s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def dewpoint(t, rh):
    if t is None or rh is None or rh <= 0:
        return None
    g = math.log(rh / 100.0) + 17.62 * t / (243.12 + t)
    return round(243.12 * g / (17.62 - g), 1)


def parse(html):
    """(地上行, 指定気圧面行) の levels を返す。"""
    rows = []
    for r in ROW.findall(html):
        c = CELL.findall(r)
        if len(c) == 6:
            rows.append([_num(x) for x in c])
    levels = []
    for i, (p, h, t, rh, spd, d) in enumerate(rows):
        if p is None or t is None:
            continue
        # 先頭1行が地上(気圧が1000付近の小数)。指定気圧面は整数の気圧値。
        lv = dict(p=p, t=t, td=dewpoint(t, rh), dir=d, spd=spd, h=h, src="JMA")
        if i == 0:
            lv["sfc"] = True
        levels.append(lv)
    return levels


def fetch_levels(point, year, month, day, hour_jst, timeout=30):
    u = URL.format(y=year, m=month, d=day, h=hour_jst, p=point)
    req = urllib.request.Request(u, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        html = r.read().decode("utf-8", "ignore")
    return parse(html)


def fetch_decoded(stations, year, month, day, pause=0.5):
    """stations: 地点番号のリスト。{(地点, day, 0|12): {"unit": "m/s", "levels": [...]}}。
    JST 9時→00Z, 21時→12Z。取得失敗や空は結果に含めない。"""
    out = {}
    for stn in stations:
        for hour_jst, z in ((9, 0), (21, 12)):
            try:
                lv = fetch_levels(stn, year, month, day, hour_jst)
            except Exception as e:  # ネットワーク失敗は欠測扱い
                print(f"[WARN] JMA {stn} {day}日{hour_jst}時: {e}")
                lv = []
            if lv:
                out[(stn, day, z)] = {"unit": "m/s", "levels": lv}
            time.sleep(pause)
    return out
