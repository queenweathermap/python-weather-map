"""15地点×(00Z/12Z)のStüve線図を1枚に合成する。電文が足りない枠は「データなし」。

build_grid(day, out_path, raw_dir) -> dict(地点番号: [00Zの状態, 12Zの状態])
状態: "ok" 描画 / "partial" 電文はあるが図にできない / "none" 電文なし
"""
import os
import sys
from datetime import datetime, timezone
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
import stuve_plot as sp  # noqa: E402

STATIONS = [("稚内", "47401"), ("札幌", "47412"), ("釧路", "47418"),
            ("秋田", "47582"), ("輪島", "47600"), ("館野", "47646"),
            ("八丈島", "47678"), ("松江", "47741"), ("潮岬", "47778"),
            ("福岡", "47807"), ("鹿児島", "47827"), ("名瀬", "47909"),
            ("石垣島", "47918"), ("南大東島", "47945"), ("父島", "47971")]
FONTS = ["/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
CELL_W, CELL_H = 520, 640
MIN_LOWER_LEVELS = 6  # 300hPaより下で気温が報じられた層数の下限(これ未満は図にしない)


def _font(size):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def usable(levels):
    return sum(1 for l in levels if l.get("t") is not None and l["p"] >= 300) >= MIN_LOWER_LEVELS


COORDS = {  # IGRA2 地点表(NOAA/NCEI)の緯度・経度
    "47401": (45.4153, 141.6786), "47412": (43.0600, 141.3286), "47418": (42.9861, 144.3772),
    "47582": (39.7172, 140.0994), "47600": (37.3914, 136.8953), "47646": (36.0581, 140.1258),
    "47678": (33.1217, 139.7792), "47741": (35.4572, 133.0656), "47778": (33.4503, 135.7572),
    "47807": (33.5822, 130.3764), "47827": (31.5550, 130.5480), "47909": (28.3850, 129.4947),
    "47918": (24.3367, 124.1644), "47945": (25.8289, 131.2286), "47971": (27.0922, 142.1914),
}
GAP = 8          # 同じ地点の00Zと12Zの間隔
GUTTER = 120     # 地点(00Z+12Zの組)どうしの横の余白
HEAD = 130       # 各行の上の見出し(地点名・緯度経度)
ROW_GAP = 60     # 行どうしの縦の余白
MARGIN = 30


def _cell(day, hour, stn, decoded):
    """(PIL画像, 状態) を返す。地点名は見出しに出すのでセル内には入れない。"""
    v = decoded.get((stn, day, hour))
    if v and usable(v["levels"]):
        buf = BytesIO()
        sp.plot_stuve(v["levels"], f"{day:02d}日 {hour:02d}Z", buf, v["unit"])
        buf.seek(0)
        im = Image.open(buf).convert("RGB")
        return im.resize((CELL_W, int(im.height * CELL_W / im.width))), "ok"
    im = Image.new("RGB", (CELL_W, CELL_H), "white")
    d = ImageDraw.Draw(im)
    for txt, y, sz in (("データなし", CELL_H // 2 - 30, 44), (f"{day:02d}日 {hour:02d}Z", CELL_H // 2 + 30, 24)):
        f = _font(sz)
        w = d.textlength(txt, font=f)
        d.text(((CELL_W - w) / 2, y), txt, font=f, fill=(0, 0, 0))
    return im, "none" if not v else "partial"


def _latlon(stn):
    lat, lon = COORDS[stn]
    return f"北緯{lat:.2f}°　東経{lon:.2f}°"


def build_grid(day, out_path, raw_dir=None, cols=3, decoded=None,
               source="気象庁 高層気象観測(TEMP電文)"):
    """out_path はパスでもBytesIOでも可。decoded を渡せば raw_dir は不要。
    レイアウト: 3地点/行。各地点は 00Z(左)+12Z(右) の組で、組どうしは大きく空ける。
    地点名(大)と緯度経度は左(00Z)の上にだけ書く。"""
    if decoded is None:
        raise ValueError("decoded が必要")
    rows = (len(STATIONS) + cols - 1) // cols
    foot = 80
    block_w = 2 * CELL_W + GAP
    W = 2 * MARGIN + cols * block_w + (cols - 1) * GUTTER
    H = MARGIN + rows * (HEAD + CELL_H + ROW_GAP) + foot
    canvas = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(canvas)
    f_name, f_sub = _font(64), _font(26)
    status = {}
    for i, (name, stn) in enumerate(STATIONS):
        r, c = divmod(i, cols)
        x0 = MARGIN + c * (block_w + GUTTER)
        y0 = MARGIN + r * (HEAD + CELL_H + ROW_GAP)
        d.text((x0 + 6, y0 + 6), name, font=f_name, fill=(0, 0, 0))
        d.text((x0 + 8, y0 + 86), f"{stn}　{_latlon(stn)}", font=f_sub, fill=(90, 90, 90))
        status[stn] = []
        for k, hour in enumerate((0, 12)):
            im, st = _cell(day, hour, stn, decoded)
            status[stn].append(st)
            canvas.paste(im, (x0 + k * (CELL_W + GAP), y0 + HEAD))
    now = datetime.now(timezone.utc)
    note = f"作成日時: {now:%Y年%m月%d日 %H:%M} UTC　出典: {source}　作成: 177chart"
    f = _font(26)
    d.text((W - d.textlength(note, font=f) - MARGIN, H - foot + 24), note, font=f, fill=(90, 90, 90))
    canvas.save(out_path, format="PNG", optimize=True)
    return status

