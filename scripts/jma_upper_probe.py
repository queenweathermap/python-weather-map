#!/usr/bin/env python3
"""気象庁 高層(確定データ)の公開時刻を実測する。

実行のたびに、JST今日から3日前までの 00Z/12Z ごとに「取得できた地点数(15中)」を表示する。
ログの `PROBE` 行を日ごとに見比べれば、各回が観測の何時間後に揃うかが分かる。
配信はしない(読み取りのみ)。
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.utils import jma_upper, stuve_grid  # noqa: E402

JST = timezone(timedelta(hours=9))


def main() -> int:
    stations = [s for _, s in stuve_grid.STATIONS]
    now = datetime.now(JST)
    lines = []
    for back in range(4):
        d = now - timedelta(days=back)
        r = jma_upper.fetch_decoded(stations, d.year, d.month, d.day, pause=0.2)
        for h in (0, 12):
            n = sum(1 for (s, dd, hh), v in r.items() if hh == h and stuve_grid.usable(v["levels"]))
            obs = d.replace(hour=9 if h == 0 else 21, minute=0, second=0, microsecond=0)
            age = (now - obs).total_seconds() / 3600
            lines.append(f"PROBE {now:%Y-%m-%d %H:%M} JST  観測日{d:%m/%d} {h:02d}Z  {n:2d}/15地点  観測から{age:5.1f}時間後")
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("```\n" + "\n".join(lines) + "\n```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
