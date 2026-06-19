#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5時・11時・17時（JST）に秋田県の気象情報3画面をスクリーンショットして Discord に送る。
"""
import json
import os
import sys
import time
import urllib.request
import uuid

from playwright.sync_api import sync_playwright

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WARNING_WEBHOOK_URL", "")

PAGES = [
    {
        "title": "秋田県の早期注意情報（警報級の可能性）",
        "url": "https://www.jma.go.jp/bosai/probability/#area_type=offices&area_code=050000&lang=ja",
        "filename": "probability.png",
    },
    {
        "title": "秋田県の時系列情報（明日までの警報等の見通し）",
        "url": "https://www.jma.go.jp/bosai/warning_timeline/#area_type=offices&area_code=050000&efilter=all&lfilter=all",
        "filename": "warning_timeline.png",
    },
    {
        "title": "秋田県の府県気象防災速報・気象解説情報等",
        "url": "https://www.jma.go.jp/bosai/information/#area_type=offices&area_code=050000&format=table&offices_page=0",
        "filename": "information.png",
    },
    {
        "title": "林野火災注意報・警報用 気象情報収集支援 konno-system",
        "url": "https://konno-system.wew.jp/forest_fire_alert/portal.php",
        "screenshot_url": "https://konno-system.wew.jp/forest_fire_alert/akita_get_information_today.php",
        "filename": "forest_fire.png",
    },
]


def take_screenshots():
    screenshots = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
        )
        page = context.new_page()
        for item in PAGES:
            print(f"撮影中: {item['title']}", flush=True)
            page.goto(item.get("screenshot_url", item["url"]))
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            # SPA のハッシュルーティングが処理されるまで待つ。
            # 404テキストが消えるか、最大20秒待機。
            for _ in range(10):
                time.sleep(2)
                is_404 = page.evaluate(
                    "() => document.body.innerText.includes('指定されたページは存在しません')"
                )
                if not is_404:
                    break
            img_bytes = page.screenshot(full_page=True)
            screenshots.append({**item, "data": img_bytes})
        browser.close()
    return screenshots


def send_discord_with_image(title, link_url, image_bytes, filename):
    boundary = uuid.uuid4().hex
    payload_json = json.dumps(
        {"content": f"**[{title}](<{link_url}>)**"},
        ensure_ascii=False,
    )
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n"
        f"{payload_json}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + image_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "akita-weather-warning/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.status


def main():
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WARNING_WEBHOOK_URL が未設定です", file=sys.stderr)
        sys.exit(1)

    screenshots = take_screenshots()

    for s in screenshots:
        status = send_discord_with_image(s["title"], s["url"], s["data"], s["filename"])
        print(f"送信: {s['title']} → {status}", flush=True)
        time.sleep(1)  # レート制限対策


if __name__ == "__main__":
    main()
