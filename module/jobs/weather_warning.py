#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5時・11時・17時（JST）に秋田県の気象情報3画面をスクリーンショットして Discord に送る。
同じ時刻に、鷹巣・秋田・横手のJMAアメダス時系列詳細(module.jobs.amedas.main())も
1つのメッセージにまとめて投稿する(2026-09-16追加。従来#amedasにのみ配信していた
JMAアメダスを、このjma-warningチャンネルにも同じタイミングで揃える)。
Discordに投稿した画像は全てR2へアップロードし、Notionにも1件アーカイブする
(2026-09-18変更。Notionには書き込まず、鷹巣・秋田・横手のR2/Notion記録は
scripts/wcn_amedas.py側で別途行う分担だったが、Discordと記録内容を揃えるため
こちらに一本化した)。
"""
import json
import os
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone, timedelta

from playwright.sync_api import sync_playwright

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WARNING_WEBHOOK_URL", "")

JST = timezone(timedelta(hours=9))

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
            try:
                page.goto(item.get("screenshot_url", item["url"]), timeout=30000)
            except Exception as e:
                print(f"スキップ（接続失敗）: {item['title']} — {e}", flush=True)
                continue
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


def send_discord_multi(content, images):
    """images: [(filename, bytes), ...] を1メッセージにまとめて投稿する。"""
    boundary = uuid.uuid4().hex
    payload_json = json.dumps({"content": content}, ensure_ascii=False)

    parts = [
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="payload_json"\r\n'
            f"Content-Type: application/json\r\n\r\n"
            f"{payload_json}\r\n"
        ).encode("utf-8")
    ]
    for i, (filename, data) in enumerate(images):
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="files[{i}]"; filename="{filename}"\r\n'
                f"Content-Type: image/png\r\n\r\n"
            ).encode("utf-8")
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)

    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "akita-weather-warning/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.status


def fetch_amedas_detail():
    """鷹巣・秋田・横手のJMAアメダス時系列詳細画像を取得して返す。Discordへは
    main()側で気象警報スクリーンショットと1つのメッセージにまとめて投稿する
    ため、ここではpost_discord/post_notionとも無効化する(post_notionは
    main()側個別ではなく、main()呼び出し元がDiscordと同じ内容で1件に
    まとめてNotionへ書くため)。R2 urlsはmain()側が常にアップロードして返す
    ものをそのまま受け取り、警報スクショと合わせてNotionアーカイブに使う
    (2026-09-18変更)。"""
    try:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.path.insert(0, repo_root)
        from module.jobs.amedas import main as amedas_main, JMA_AMEDAS_URL
        detail_imgs, r2_urls = amedas_main(post_discord=False, post_notion=False)
        return detail_imgs, r2_urls, JMA_AMEDAS_URL
    except Exception as e:
        print(f"[WARN] JMAアメダス取得に失敗: {e}", file=sys.stderr)
        return [], [], ""


def _upload_r2(items):
    """(filename, bytes) リストをR2にアップしてURLリストを返す。R2_ENABLE=0
    または失敗時は空文字を混ぜて返す。"""
    if os.environ.get("R2_ENABLE", "1").lower() not in ("1", "true", "yes", "on"):
        return []
    try:
        from module.utils.r2_utils import put_bytes, make_url
    except ImportError:
        print("[WARN] r2_utils not available", file=sys.stderr)
        return []

    prefix = os.environ.get("R2_PREFIX", "jma-warning").strip().strip("/")
    day_hm = datetime.now(JST).strftime("%Y%m%d/%H%M")
    urls = []
    for fname, data in items:
        key = f"{prefix}/{day_hm}/{fname}"
        try:
            put_bytes(key, data, content_type="image/png")
            urls.append(make_url(key))
            print(f"[OK] R2 upload: {key}")
        except Exception as e:
            print(f"[WARN] R2 upload {key}: {e}", file=sys.stderr)
    return urls


def _nearest_scheduled_slot_jst(now, slots):
    """(hour, minute)のリストから、nowに最も近いスケジュール時刻を返す
    (実行が数分〜数時間遅れても、YMLプロパティは定刻表示にするため)。"""
    def _circular_diff_seconds(a, b):
        diff = abs((a - b).total_seconds())
        return min(diff, 86400 - diff)

    candidates = [now.replace(hour=h, minute=m, second=0, microsecond=0) for h, m in slots]
    return min(candidates, key=lambda t: _circular_diff_seconds(now, t))


def _archive_to_notion(links, r2_urls):
    """Discordに投稿したのと同じ画像・リンクをNotionへ1件アーカイブする。"""
    try:
        from module.utils.notion_utils import archive_to_notion
    except ImportError:
        print("[WARN] notion_utils not available", file=sys.stderr)
        return

    now = datetime.now(JST)
    yml_jst = _nearest_scheduled_slot_jst(now, [(5, 15), (11, 15), (17, 15)])
    try:
        archive_to_notion(
            title=f"秋田 注意報警報等＋アメダス詳細〔{now.strftime('%Y%m%d %H:%M')} JST〕",
            category="AMeDAS",
            r2_urls=r2_urls,
            jst_now=now,
            pwa=False,
            icon_emoji="⚠️",
            links=links,
            yml_jst=yml_jst,
        )
    except Exception as e:
        print(f"[WARN] Notionアーカイブ失敗: {e}", file=sys.stderr)


def main():
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WARNING_WEBHOOK_URL が未設定です", file=sys.stderr)
        sys.exit(1)

    screenshots = take_screenshots()
    if not screenshots:
        print("撮影できたページがありませんでした", file=sys.stderr)

    lines = ["🔗 [秋田地方気象台](<https://www.jma-net.go.jp/akita/>)"]
    links = [("秋田地方気象台", "https://www.jma-net.go.jp/akita/")]
    images = []
    for s in screenshots:
        lines.append(f"🔗 [{s['title']}](<{s['url']}>)")
        links.append((s["title"], s["url"]))
        images.append((s["filename"], s["data"]))

    amedas_imgs, amedas_r2_urls, amedas_url = fetch_amedas_detail()
    if amedas_imgs:
        lines.append(f"🔗 [アメダス（秋田）](<{amedas_url}>)")
        links.append(("アメダス（秋田）", amedas_url))
        images.extend(amedas_imgs)

    if images:
        status = send_discord_multi("\n".join(lines), images)
        print(f"送信: {len(images)}枚まとめて → {status}", flush=True)

        screenshot_items = [(s["filename"], s["data"]) for s in screenshots]
        r2_urls = _upload_r2(screenshot_items) + amedas_r2_urls
        _archive_to_notion(links, r2_urls)
    else:
        print("送信する画像がありませんでした", file=sys.stderr)


if __name__ == "__main__":
    main()
