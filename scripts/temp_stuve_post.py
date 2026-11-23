#!/usr/bin/env python3
"""気象庁TEMP電文(R2に蓄積)から15地点のStüve線図を合成して配信する。

emagram_discord.py(Wyoming版)の後継。配信の流れ(R2・Notion・PWA/メール)は
同じものを使う。実行はUTC 19:00(JST翌04:00)を想定し、当日UTCの00Z/12Zをまとめる。

DRY_RUN=1 の間は配信せず、R2の preview/ にだけ置いてURLを表示する(既定は1)。
本番切替は workflow の env で DRY_RUN を "0" にする。
"""
import os
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image  # noqa: E402

from module.utils.r2_utils import put_bytes, get_bytes, list_keys_with_prefix, make_url  # noqa: E402
from module.utils import stuve_grid  # noqa: E402

DRY_RUN = os.environ.get("DRY_RUN", "1").strip().lower() in ("1", "true", "yes", "on")
JMA_UPPER_URL = "https://www.data.jma.go.jp/stats/etrn/upper/index.php"
THUMB_MAX_WIDTH = 1400


def load_day_texts(day_str: str) -> list:
    texts = []
    for k in sorted(list_keys_with_prefix(f"temp_raw/{day_str}/")):
        b = get_bytes(k)
        if b:
            texts.append(b.decode("ascii", "replace"))
    return texts


def main() -> int:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    dt12 = today.replace(hour=12)
    day_str = today.strftime("%Y%m%d")

    texts = load_day_texts(day_str)
    print(f"raw bulletins loaded: {len(texts)} ({day_str})")
    decoded = stuve_grid.decode_texts(texts)
    buf = BytesIO()
    status = stuve_grid.build_grid(today.day, buf, decoded=decoded)
    combined = buf.getvalue()
    ok = sum(1 for v in status.values() for s in v if s == "ok")
    print(f"cells drawn: {ok}/{len(status) * 2}")
    for stn, v in status.items():
        print(" ", stn, v)

    if ok == 0:
        print("描ける地点が1つもないため終了(配信しない)")
        return 1

    if DRY_RUN:
        key = f"preview/temp_stuve_{day_str}_{now:%H%M%S}.png"
        put_bytes(key, combined, content_type="image/png")
        print(f"DRY_RUN: preview uploaded: {make_url(key)}")
        return 0

    # ---- 本番配信 (emagram_discord と同じ経路) ----
    from scripts import emagram_discord as ed

    r2_key = f"{day_str}_{now:%H%M%S}.png"
    put_bytes(r2_key, combined, content_type="image/png")
    highres_url = make_url(r2_key)
    print(f"R2 UPLOADED: {highres_url}")

    with Image.open(BytesIO(combined)) as im:
        rgb = im.convert("RGB")
        if rgb.width > THUMB_MAX_WIDTH:
            rgb = rgb.resize((THUMB_MAX_WIDTH, int(rgb.height * THUMB_MAX_WIDTH / rgb.width)))
        tb = BytesIO()
        rgb.save(tb, format="JPEG", quality=85, optimize=True)
        thumb = tb.getvalue()

    ed.archive_to_notion(
        title=f"エマグラム　前日まとめ（{len(stuve_grid.STATIONS)}地点）",
        category="高層観測データ",
        r2_urls=[highres_url],
        jst_now=now,
        pwa=True,
        size_bytes=len(combined),
        header=f"高層観測データ {dt12.strftime('%Y/%m/%d')}まとめ",
        icon_emoji="📈",
        links=[("気象庁 過去の気象データ検索（高層）", JMA_UPPER_URL)],
        yml_jst=today.replace(hour=19),
    )
    content = (
        f"高層観測データ　{dt12.strftime('%Y/%m/%d')}まとめ\n"
        f"エマグラム 前日まとめ（{len(stuve_grid.STATIONS)}地点）\n"
        f"📥 [高解像度PNGをダウンロード（{ed.R2_RETENTION_DAYS}日間有効）](<{highres_url}>)"
    )
    ed.notify_dm_subscribers(content, thumb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
