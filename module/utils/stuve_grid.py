"""15地点×(00Z/12Z)のStüve線図を1枚に合成する。電文が足りない枠は「データなし」。

build_grid(day, out_path, raw_dir) -> dict(地点番号: [00Zの状態, 12Zの状態])
状態: "ok" 描画 / "partial" 電文はあるが図にできない / "none" 電文なし
"""
import glob
import os
import sys
from datetime import datetime, timezone
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
import temp_decode as td  # noqa: E402
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


def load_decoded(raw_dir):
    txt = ""
    for f in sorted(glob.glob(os.path.join(raw_dir, "*", "*.txt"))):
        txt += open(f, errors="replace").read() + "\n"
    return td.decode_text(txt)


def decode_texts(texts):
    """電文テキストのリスト(R2から取得した分など)をまとめてデコードする。"""
    return td.decode_text("\n".join(texts) + "\n")


def usable(levels):
    return sum(1 for l in levels if l.get("t") is not None and l["p"] >= 300) >= MIN_LOWER_LEVELS


def _cell(name, stn, day, hour, decoded):
    """(PIL画像, 状態) を返す。"""
    v = decoded.get((stn, day, hour))
    if v and usable(v["levels"]):
        buf = BytesIO()
        sp.plot_stuve(v["levels"], f"{name}  {stn}  {day:02d}日 {hour:02d}Z", buf, v["unit"])
        buf.seek(0)
        im = Image.open(buf).convert("RGB")
        return im.resize((CELL_W, int(im.height * CELL_W / im.width))), "ok"
    im = Image.new("RGB", (CELL_W, CELL_H), "white")
    d = ImageDraw.Draw(im)
    for txt, y, sz in ((f"{name}  {stn}", 40, 26), ("データなし", CELL_H // 2 - 20, 40),
                       (f"{day:02d}日 {hour:02d}Z", CELL_H // 2 + 36, 22)):
        f = _font(sz)
        w = d.textlength(txt, font=f)
        d.text(((CELL_W - w) / 2, y), txt, font=f, fill=(0, 0, 0))
    return im, "none" if not v else "partial"


def build_grid(day, out_path, raw_dir=None, cols=3, decoded=None):
    """out_path はパスでもBytesIOでも可。decoded を渡せば raw_dir は不要。"""
    if decoded is None:
        decoded = load_decoded(raw_dir)
    rows = (len(STATIONS) + cols - 1) // cols
    foot = 70
    W, H = cols * 2 * CELL_W, rows * CELL_H + foot
    canvas = Image.new("RGB", (W, H), "white")
    status = {}
    for i, (name, stn) in enumerate(STATIONS):
        r, c = divmod(i, cols)
        status[stn] = []
        for k, hour in enumerate((0, 12)):
            im, st = _cell(name, stn, day, hour, decoded)
            status[stn].append(st)
            canvas.paste(im, ((c * 2 + k) * CELL_W, r * CELL_H))
    d = ImageDraw.Draw(canvas)
    now = datetime.now(timezone.utc)
    note = f"作成日時: {now:%Y年%m月%d日 %H:%M} UTC　出典: 気象庁 高層気象観測(TEMP電文)　作成: 177chart"
    f = _font(24)
    d.text((W - d.textlength(note, font=f) - 20, H - foot + 20), note, font=f, fill=(90, 90, 90))
    canvas.save(out_path, format="PNG", optimize=True)
    return status


if __name__ == "__main__":
    import matplotlib
    matplotlib.rcParams["font.family"] = "Hiragino Sans"
    st = build_grid(int(sys.argv[1]), sys.argv[2], os.path.expanduser("~/weather_data/temp_raw"))
    for k, v in st.items():
        print(k, v)
