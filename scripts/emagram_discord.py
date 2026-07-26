#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# scripts/emagram_discord.py
#
# 気象庁指定の高層観測15地点のエマグラム（Stuve線図）を
# ワイオミング大学 (weather.arcc.uwyo.edu) の高層観測アーカイブから取得し、
# Discordへ配信する。
#
# 観測は 00Z(09時JST) / 12Z(21時JST) の1日2回。
# データ反映まで余裕を見て、観測から2時間後（11時/23時JST）に実行する想定。
#
# 画像は静的URL（/upperair/imgs/{YYYYMMDDHH}.{地点番号}.stuve.png）に
# 直接は存在せず、/wsgi/sounding?...type=PNG:STUVE... への初回アクセス時に
# サーバー側で遅延生成される。そのため必ず一度 /wsgi/sounding を叩いてから
# 静的URLを参照する。

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone

import requests

STATIONS = [
    ("47401", "稚内"),
    ("47412", "札幌"),
    ("47418", "釧路"),
    ("47582", "秋田"),
    ("47600", "輪島"),
    ("47646", "館野"),
    ("47678", "八丈島"),
    ("47741", "松江"),
    ("47778", "潮岬"),
    ("47807", "福岡"),
    ("47827", "鹿児島"),
    ("47909", "名瀬"),
    ("47918", "石垣島"),
    ("47945", "南大東島"),
    ("47971", "父島"),
]

BASE = "https://weather.arcc.uwyo.edu"
SOUNDING_URL = BASE + "/wsgi/sounding"
IMG_SRC_RE = re.compile(r'<img src="(/upperair/imgs/[^"]+\.png)">')

MAX_EMBEDS_PER_MESSAGE = 10
REQUEST_TIMEOUT_SECONDS = 60
DISCORD_TIMEOUT_SECONDS = 20


def target_sounding_time() -> datetime:
    """直近の観測時刻（00Z or 12Z）を返す。"""
    now = datetime.now(timezone.utc)
    hour = 0 if now.hour < 12 else 12
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


def fetch_image_url(stnm: str, dt: datetime) -> str | None:
    """指定地点・時刻のStuve画像を生成させ、静的URLを返す（データが無ければNone）。"""
    params = {
        "datetime": dt.strftime("%Y-%m-%d %H:00:00"),
        "id": stnm,
        "type": "PNG:STUVE",
        "src": "FM35",
    }
    try:
        r = requests.get(SOUNDING_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        print(f"ERROR: {stnm} 取得中に例外が発生しました: {exc}", file=sys.stderr)
        return None

    if r.status_code != 200:
        print(f"SKIP: {stnm} status={r.status_code}")
        return None

    m = IMG_SRC_RE.search(r.text)
    if not m:
        print(f"SKIP (データなし): {stnm}")
        return None

    return BASE + m.group(1)


def post_batch(webhook_url: str, dt: datetime, batch) -> bool:
    embeds = []
    for name, url in batch:
        embeds.append({
            "title": name,
            "image": {"url": url},
            "color": 3066993,
        })

    payload = {
        "username": "エマグラム",
        "content": f"🌡️ **エマグラム / {dt.strftime('%Y-%m-%d %H')}Z**",
        "embeds": embeds,
    }

    try:
        r = requests.post(webhook_url, json=payload, timeout=DISCORD_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        print(f"ERROR: Discord投稿中に例外が発生しました: {exc}", file=sys.stderr)
        return False

    if 200 <= r.status_code < 300:
        return True

    print(f"ERROR: Discord投稿失敗 status={r.status_code} body={r.text[:500]}", file=sys.stderr)
    return False


def main() -> int:
    webhook_url = os.environ.get("DISCORD_EMAGRAM_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("ERROR: DISCORD_EMAGRAM_WEBHOOK_URL未設定", file=sys.stderr)
        return 1

    dt = target_sounding_time()

    available = []
    for stnm, name in STATIONS:
        url = fetch_image_url(stnm, dt)
        if url:
            available.append((f"{name}（{stnm}）", url))

    if not available:
        print(f"NO DATA: {dt.strftime('%Y-%m-%d %H')}Z のデータがまだありません")
        return 0

    ok = True
    for i in range(0, len(available), MAX_EMBEDS_PER_MESSAGE):
        batch = available[i:i + MAX_EMBEDS_PER_MESSAGE]
        if post_batch(webhook_url, dt, batch):
            print(f"POSTED: {', '.join(name for name, _ in batch)}")
        else:
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
