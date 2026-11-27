#!/usr/bin/env python3
"""気象庁の高層観測データ(確定値)から15地点のStüve線図を合成して前日まとめとして配信する。

気象庁の「過去の気象データ検索(高層)」は観測の翌日〜翌々日に反映される。
JST今日の前日を対象日Dとし、(D-1日12Z, D日00Z)を左右に並べる(半日ずらし)。
公開は日単位のため、D日分が出そろってから実行すること(時刻は公開時刻の実測で決める)。
データ元が公的で15地点の欠測が最小(0〜2地点)になるのが利点。速報性は無い。

DRY_RUN=1(既定)の間は配信せず、R2の preview/ にだけ置いてURLを表示する。
本番切替は workflow の env で DRY_RUN を "0" にする。
TARGET_DATE=YYYYMMDD で対象日を指定できる(検証用)。
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image  # noqa: E402

from module.utils.r2_utils import put_bytes, get_bytes, make_url  # noqa: E402
from module.utils import stuve_grid, jma_upper  # noqa: E402

DRY_RUN = os.environ.get("DRY_RUN", "1").strip().lower() in ("1", "true", "yes", "on")
JMA_UPPER_URL = "https://www.data.jma.go.jp/stats/etrn/upper/index.php"
SOURCE = "気象庁 高層気象観測(確定データ)"
THUMB_MAX_WIDTH = 1400
JST = timezone(timedelta(hours=9))


def target_date(now: datetime) -> datetime:
    t = os.environ.get("TARGET_DATE", "").strip()
    if t:
        return datetime.strptime(t, "%Y%m%d").replace(tzinfo=JST)
    return (now.astimezone(JST) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def marker_key(d: datetime) -> str:
    return f"state/jma_stuve_delivered_{d:%Y%m%d}"


def main() -> int:
    now = datetime.now(timezone.utc)
    d = target_date(now)
    # 定期実行は1日に何度か走らせ、データが出そろった最初の回で配信する。
    # 配信済みの目印(R2)があれば何もしない。手動(TARGET_DATE指定/DRY_RUN)は目印を見ない。
    use_marker = not DRY_RUN and not os.environ.get("TARGET_DATE", "").strip()
    if use_marker and get_bytes(marker_key(d)) is not None:
        print(f"{d:%Y-%m-%d} 分は配信済みのためスキップ")
        return 0
    stations = [s for _, s in stuve_grid.STATIONS]
    print(f"対象日(JST): {d:%Y-%m-%d}  DRY_RUN={DRY_RUN}")
    # 半日ずらし: 前日12Z(左) + 対象日00Z(右)。対象日00Zを主役にして「前日まとめ」とする。
    prev = d - timedelta(days=1)
    cells = ((prev.day, 12), (d.day, 0))
    decoded = jma_upper.fetch_decoded(stations, prev.year, prev.month, prev.day)
    decoded.update(jma_upper.fetch_decoded(stations, d.year, d.month, d.day))
    buf = BytesIO()
    status = stuve_grid.build_grid(d.day, buf, decoded=decoded, source=SOURCE, cells=cells)
    combined = buf.getvalue()
    ok = sum(1 for v in status.values() for s in v if s == "ok")
    print(f"cells drawn: {ok}/{len(status) * 2}")
    for stn, v in status.items():
        print(" ", stn, v)

    # 反映前(全滅に近い)の日に誤って配信しない。通常は13/15地点×2=26前後。
    if ok < 20:
        print("描けたセルが少なすぎる(気象庁側の反映待ちの可能性)ため配信しない")
        # 反映待ちは次の回で再挑戦する。対象日の翌日22時(JST)を過ぎても出ない場合だけ失敗扱いにして気づけるようにする。
        late = now.astimezone(JST) >= d + timedelta(days=1, hours=22)
        return 1 if late else 0

    day_str = d.strftime("%Y%m%d")
    if DRY_RUN:
        key = f"preview/jma_stuve_{day_str}_{now:%H%M%S}.png"
        put_bytes(key, combined, content_type="image/png")
        print(f"DRY_RUN: preview uploaded: {make_url(key)}")
        # Actionsの成果物としても残す(workflowのupload-artifactが拾う)
        out_dir = REPO_ROOT / "preview_out"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "jma_stuve.png").write_bytes(combined)
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

    # 表記はウィンドプロファイラ(「ウィンドプロファイラ（33地点）: 前日まとめ（11/23）」)に揃える:
    # 相対表現＋観測日。定期実行は常にJST今日の前日(D)を扱う。
    label = f"{d:%Y/%m/%d}"
    ed.archive_to_notion(
        title=f"エマグラム（{len(stuve_grid.STATIONS)}地点）: 前日まとめ（{d:%m/%d}）",
        category="高層観測データ",
        r2_urls=[highres_url],
        jst_now=now,
        memo="気象庁の確定データ(前日12Z+前日00Z、翌日に配信)",
        pwa=True,
        size_bytes=len(combined),
        header=f"高層観測データ {label}まとめ",
        icon_emoji="📈",
        links=[("気象庁 過去の気象データ検索（高層）", JMA_UPPER_URL)],
        yml_jst=(now.astimezone(JST)).replace(hour=17, minute=0, second=0, microsecond=0),
    )
    content = (
        f"高層観測データ　{label}まとめ\n"
        f"エマグラム {len(stuve_grid.STATIONS)}地点（気象庁の確定データ）\n"
        f"📥 [高解像度PNGをダウンロード（{ed.R2_RETENTION_DAYS}日間有効）](<{highres_url}>)"
    )
    ed.notify_dm_subscribers(content, thumb)
    put_bytes(marker_key(d), now.isoformat().encode(), content_type="text/plain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
