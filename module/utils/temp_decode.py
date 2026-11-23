"""WMO FM-35 TEMP 電文(TTAA/TTBB/TTCC/TTDD)のデコーダ(標準ライブラリのみ)。

decode_text(text) -> {(station, day, hour): {"unit": "kt"|"m/s", "levels": [...]}}
levels の各要素: dict(p=hPa, t=℃, td=℃|None, dir=度|None, spd=kt|m/s|None, h=m|None, src="TTAA"...)
風速の単位は電文ヘッダの YY が +50 なら knots、そうでなければ m/s。unit キーに入る。
"""
import re
from collections import defaultdict

# TTAA/TTCC の標準気圧面 ID -> 気圧(hPa)
STD_AA = {"00": 1000, "92": 925, "85": 850, "70": 700, "50": 500, "40": 400,
          "30": 300, "25": 250, "20": 200, "15": 150, "10": 100}
STD_CC = {"70": 70, "50": 50, "30": 30, "20": 20, "10": 10}
STD_DD = {"70": 70, "50": 50, "30": 30, "20": 20, "10": 10}  # TTDD 側も同じID体系


def _temp(g):
    """TTTDD の TTT 部。tenths 桁が偶数→正、奇数→負。"""
    if g is None or "/" in g[:3]:
        return None
    v = int(g[:3]) / 10.0
    return -v if int(g[2]) % 2 else v


def _dd(g):
    """露点差。00-50→0.0-5.0、56-99→6-49。"""
    if g is None or "/" in g[3:5]:
        return None
    d = int(g[3:5])
    if d <= 50:
        return d / 10.0
    if d >= 56:
        return float(d - 50)
    return None


def _wind(g):
    """dddff。3桁目の 1/6 等の端数は100の位として加算。"""
    if g is None or "/" in g:
        return None, None
    d, ff = int(g[:3]), int(g[3:])
    h = d % 5
    return d - h, h * 100 + ff


def _height_aa(pid, ggg):
    """標準気圧面の高度(m)。"""
    if "/" in ggg:
        return None
    v = int(ggg)
    if pid == "00":
        return -(v - 500) if v >= 500 else v
    if pid == "92":
        return v
    if pid == "85":
        return 1000 + v
    if pid == "70":
        return (3000 if v < 500 else 2000) + v
    if pid in ("50", "40"):
        return v * 10
    if pid == "30":
        return (v + (1000 if v < 500 else 0)) * 10
    return (v + 1000) * 10  # 25/20/15/10 hPa


def _split(text):
    """電文を (種別, 地点, YYGG, [グループ...]) に分ける。"""
    out = []
    for m in re.finditer(r"\b(TT[ABCD]{2}) (\d{4}[\d/]) (\d{5})((?:\s+[\d/]{3,5})+?)\s*=", text, re.S):
        out.append((m.group(1), m.group(3), m.group(2), m.group(4).split()))
    return out


def decode_text(text):
    res = defaultdict(lambda: {"levels": []})
    for kind, stn, hdr, groups in _split(text):
        yy = int(hdr[:2])
        unit = "kt" if yy >= 50 else "m/s"
        day, hour = yy % 50, int(hdr[2:4])
        s = res[(stn, day, hour)]
        s["unit"] = unit
        lv = s["levels"]
        i = 0
        if kind in ("TTAA", "TTCC"):
            table = STD_AA if kind == "TTAA" else STD_CC
            while i < len(groups):
                g = groups[i]
                if g in ("31313", "51515"):
                    break
                if g[:2] == "99" and kind == "TTAA":  # 地上
                    p = int(g[2:])
                    p = p + 1000 if p < 100 else p
                    t, w = groups[i + 1], groups[i + 2]
                    dr, sp = _wind(w)
                    lv.append(dict(p=float(p), t=_temp(t), td=_dtd(t), dir=dr, spd=sp, h=None, src=kind, sfc=True))
                    i += 3
                elif g[:2] in ("88", "77", "66") and g[2:] in ("999", "///"):
                    i += 1
                elif g[:2] == "88":     # 圏界面
                    i += 3
                elif g[:2] in ("77", "66"):  # 極大風速面(+鉛直シア群が付くことがある)
                    i += 3 if i + 2 < len(groups) and groups[i + 2][0] == "4" else 2
                elif g[:2] in table:
                    pid = g[:2]
                    if i + 1 >= len(groups):
                        break
                    t = groups[i + 1]
                    w = groups[i + 2] if i + 2 < len(groups) else None
                    dr, sp = _wind(w) if w and len(w) == 5 else (None, None)
                    h = _height_aa(pid, g[2:]) if kind == "TTAA" else None
                    lv.append(dict(p=float(table[pid]), t=_temp(t), td=_dtd(t), dir=dr, spd=sp, h=h, src=kind))
                    i += 3
                else:
                    i += 1
        else:  # TTBB / TTDD: 特異点 nnPPP TTTDD ... 21212 部で風
            sec = "T"
            while i < len(groups):
                g = groups[i]
                if g == "21212":
                    sec, i = "W", i + 1
                    continue
                if g in ("31313", "41414", "51515", "61616"):
                    break
                if i + 1 >= len(groups):
                    break
                nn, ppp = g[:2], g[2:]
                if nn[0] != nn[1] or "/" in ppp:
                    i += 1
                    continue
                p = int(ppp)
                if kind == "TTBB":
                    p = p + 1000 if p < 100 else p
                else:
                    p = p / 10.0  # TTDD は 0.1hPa 単位
                if sec == "T":
                    t = groups[i + 1]
                    lv.append(dict(p=float(p), t=_temp(t), td=_dtd(t), dir=None, spd=None, h=None, src=kind))
                else:
                    dr, sp = _wind(groups[i + 1])
                    lv.append(dict(p=float(p), t=None, td=None, dir=dr, spd=sp, h=None, src=kind, wind_only=True))
                i += 2
    return res


def _dtd(g):
    t, dd = _temp(g), _dd(g)
    return None if t is None or dd is None else round(t - dd, 1)
