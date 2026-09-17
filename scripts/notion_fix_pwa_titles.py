# -*- coding: utf-8 -*-
# =============================================================================
# scripts/notion_fix_pwa_titles.py
#
# 一回限りのメンテナンススクリプト。
#
# PWAタグ付きの過去21日分の行を、今日のタイトル/ヘッダ形式にそろえる。
# タイトルは区分から決め打ち、ヘッダはR2 URLに埋め込まれた実際の初期値・
# 投稿時刻から、weather_map.py本体と同じ関数で再計算する(表記を完全に
# 一致させるため、ロジックを重複実装せずそのままimportして使う)。
#
# 実行後は不要になるため、ワークフローごと削除してよい。
# =============================================================================

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import requests

from module.utils.notion_utils import API_BASE, _headers, _must_env
from module.jobs.weather_map import (
    numeric_fresh_issue_label,
    weekly_forecast_issue_label,
    issue_time_overlay_text,
)

JST = timezone(timedelta(hours=9))

TITLE_BY_CATEGORY = {
    "全部入り天気図": "全部入り天気図　高層天気図・数値予報天気図 結合図",
    "中期予報資料": "中期予報資料　週間予報＋2週間気温予報 結合図",
    "長期予報資料": "長期予報資料　1ヶ月予報 結合図",
}


def parse_weathermap_r2(url: str):
    """.../weathermap/YYYYMMDD/RJTD_DDHHMM_HHMMSS/FILENAME.png から
    (初期値のJST datetime, 実際の投稿JST datetime) を復元する。"""
    m = re.search(r"/weathermap/(\d{4})(\d{2})(\d{2})/RJTD_(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/", url)
    if not m:
        return None
    fy, fm, fd, nd, nh, nmin, ah, amin, asec = (int(g) for g in m.groups())
    nominal_dt = datetime(fy, fm, fd, nh, nmin, tzinfo=JST)
    actual_dt = datetime(fy, fm, fd, ah, amin, asec, tzinfo=JST)
    # 21:00サイクルの追いかけ実行(05:xx頃)は日付をまたいでいるため+1日する。
    if nh == 21 and ah < 12:
        actual_dt = actual_dt + timedelta(days=1)
    return nominal_dt, actual_dt


def parse_koso_r2(url: str):
    """エマグラム/ウィンドプロファイラのR2 URLから対象日を復元する。
    戻り値: (subtype, date_str) subtypeは 'emagram' か 'windprofiler'。"""
    m = re.search(r"/emagram/(\d{4})(\d{2})(\d{2})_\d{6}\.png", url)
    if m:
        y, mo, d = m.groups()
        return "emagram", f"{y}/{mo}/{d}"
    m = re.search(r"/windprofiler/(\d{4})(\d{2})(\d{2})_daily_grid\.png", url)
    if m:
        y, mo, d = m.groups()
        return "windprofiler", f"{y}/{mo}/{d}"
    return None


def compute_title_and_header(tags, r2_url):
    for cat, title in TITLE_BY_CATEGORY.items():
        if cat in tags:
            parsed = parse_weathermap_r2(r2_url)
            if not parsed:
                return None
            nominal_dt, actual_dt = parsed
            if cat == "全部入り天気図":
                header = issue_time_overlay_text(nominal_dt, now=actual_dt)
            elif cat == "中期予報資料":
                header = weekly_forecast_issue_label(nominal_dt)
            else:  # 長期予報資料
                monthly_init = (actual_dt - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
                header = numeric_fresh_issue_label(monthly_init)
            return title, header

    if "高層観測" in tags:
        parsed = parse_koso_r2(r2_url)
        if not parsed:
            return None
        subtype, date_str = parsed
        header = f"高層観測データ {date_str}まとめ"
        if subtype == "emagram":
            return "高層観測データ　エマグラム　前日まとめ（15地点）", header
        else:
            return "高層観測データ　ウィンドプロファイラ　前日まとめ（33地点）", header

    return None


def iter_pwa_pages(database_id: str):
    body = {
        "filter": {
            "and": [
                {"property": "区分", "multi_select": {"contains": "PWA"}},
                {
                    "property": "配信日時",
                    "date": {"on_or_after": (datetime.now(JST) - timedelta(days=21)).isoformat()},
                },
            ]
        },
        "page_size": 100,
    }
    while True:
        r = requests.post(
            f"{API_BASE}/databases/{database_id}/query",
            headers=_headers(),
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            props = page["properties"]
            tags = [t["name"] for t in props.get("区分", {}).get("multi_select", [])]
            r2_url = props.get("R2 URL", {}).get("url") or ""
            yield page["id"], tags, r2_url
        if not data.get("has_more"):
            return
        body["start_cursor"] = data["next_cursor"]


def main() -> None:
    database_id = _must_env("NOTION_DATABASE_ID")

    pages = list(iter_pwa_pages(database_id))
    print(f"[INFO] {len(pages)} PWA pages in last 21 days")

    ok = 0
    skipped = []
    failed = []
    for i, (page_id, tags, r2_url) in enumerate(pages, start=1):
        result = compute_title_and_header(tags, r2_url)
        if result is None:
            skipped.append((page_id, tags, r2_url))
            continue
        title, header = result

        props = {
            "タイトル": {"title": [{"type": "text", "text": {"content": title}}]},
        }
        if header:
            props["ヘッダ"] = {"rich_text": [{"type": "text", "text": {"content": header}}]}

        try:
            r = requests.patch(
                f"{API_BASE}/pages/{page_id}",
                headers=_headers(),
                json={"properties": props},
                timeout=30,
            )
            r.raise_for_status()
            ok += 1
            if i % 50 == 0:
                print(f"[{i}/{len(pages)}] ok={ok} skipped={len(skipped)} failed={len(failed)}")
        except Exception as e:
            print(f"[NG] {page_id}: {e}")
            failed.append(page_id)

    print(f"\n[DONE] ok={ok} skipped={len(skipped)} failed={len(failed)} total={len(pages)}")
    if skipped:
        print("[SKIPPED (unparseable R2 URL)]")
        for pid, tags, url in skipped:
            print(f"  {pid} tags={tags} r2={url}")
    if failed:
        print("[FAILED PAGE IDS]")
        for pid in failed:
            print(f"  {pid}")


if __name__ == "__main__":
    main()
