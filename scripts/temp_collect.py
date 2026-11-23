#!/usr/bin/env python3
"""NWS tgftp の気象庁(RJTD)発TEMP電文を取得し、更新があればR2へ蓄積する。

tgftp は同名ファイルへ最新の電文を上書きするため、観測の前後で5分おきに
GitHub Actions (temp-collect.yml) から呼ぶ。キーは Last-Modified から決めるので、
同じ更新を重複して保存しない:
    temp_raw/YYYYMMDD/<ファイル名>_<HHMMSS>.txt   (R2_PREFIX が先頭に付く)
"""
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from module.utils.r2_utils import put_bytes, list_keys_with_prefix  # noqa: E402

BASE = "https://tgftp.nws.noaa.gov/data/raw"
# us=TTAA(標準面) uk=TTBB(特異点) ul=TTCC(上層標準面)。um(TTDD)はRJTD発のファイルが無い。
# pa(太平洋域)は日本の15地点を含まないので取らない。
FILES = [f"{k}/{k}jp01.rjtd..txt" for k in ("us", "uk", "ul")]
UA = "weather-temp-collector/1.0"


def main() -> int:
    saved = 0
    existing: dict[str, set] = {}
    for f in FILES:
        req = urllib.request.Request(f"{BASE}/{f}", headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                lm = r.headers.get("Last-Modified", "")
        except urllib.error.HTTPError as e:
            print(f"{f}: HTTP {e.code}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"{f}: {e}", file=sys.stderr)
            continue
        try:
            t = parsedate_to_datetime(lm).astimezone(timezone.utc)
        except Exception:
            t = datetime.now(timezone.utc)
        day = t.strftime("%Y%m%d")
        if day not in existing:
            existing[day] = set(list_keys_with_prefix(f"temp_raw/{day}/"))
        key = f"temp_raw/{day}/{f.split('/')[1].replace('..txt', '')}_{t:%H%M%S}.txt"
        if key in existing[day]:
            continue
        put_bytes(key, body, content_type="text/plain", cache_control="no-store")
        saved += 1
        print(f"saved {key} ({len(body)}B)")
    print(f"done saved={saved}/{len(FILES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
