# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_weathercaster.py
#
# Weathercaster（会員ページ）PDFをDL→JPG化 → R2へアップ → Notion DBへ記録
# - Notion DB：代表画像1枚＋toggle内に全文画像を展開
# - メール送信（JPGを複数添付：ZIPにしない）
# - Slack通知は mail_utils.py に集約（slack_modeで制御）
#
# 必須ENV:
#   WEATHERCASTER_USER, WEATHERCASTER_PASS
#
# R2 ENV（R2+Notionを使うなら必須）:
#   R2_ACCOUNT_ID
#   R2_ACCESS_KEY_ID
#   R2_SECRET_ACCESS_KEY
#   R2_BUCKET
#   ASSET_BASE_URL          # 例: https://<your-bucket>.<something>.r2.dev   (末尾スラッシュ無し推奨)
#   R2_PREFIX               # 任意（例: "jma-adv" など）
#   R2_ENABLE=1             # 任意（0でR2アップしない）
#
# Notion ENV（DBに書くなら必須）:
#   NOTION_TOKEN
#   NOTION_DATABASE_ID      # wx 天気図 DB の database_id
#   NOTION_ENABLE=1         # 任意（0でNotion書き込みしない）
#
# Notion プロパティ名（DB側の名前が違う場合に上書き可）:
#   NOTION_PROP_TITLE="名前"
#   NOTION_PROP_MODEL="区分"
#   NOTION_PROP_INIT_JST="初期時刻（JST）"
#   NOTION_PROP_MEMO="メモ"
#   # 任意:
#   NOTION_PROP_R2URL="R2 URL"
#   NOTION_PROP_AUTOGEN="自動生成"
#
# Mail ENV（mail_utils.py準拠）:
#   FROM_EMAIL, TO_EMAIL(or MAIL_TO), SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD
#   MAIL_SUBJECT_PREFIX
#   MAIL_ATTACH_AS_ZIP="0" 推奨（ZIP禁止）
#   MAX_MAIL_SIZE_MB="100" 推奨（サイズ超でZIPにならないように）
#
# Slack ENV（mail_utils.py準拠）:
#   SLACK_BOT_TOKEN, SLACK_CHANNEL_ID
#   MAIL_SLACK_NOTIFY="1"
#
# =============================================================================

from __future__ import annotations

import io
import os
import shutil
from datetime import datetime, timezone
from typing import List, Tuple, Optional, Dict, Any

import requests
from pdf2image import convert_from_bytes

from module.utils.mail_utils import send_mail

# R2（scripts/ 直下に r2_utils.py がある想定）
from r2_utils import put_bytes, make_url

# Notion（module/utils/notion_utils.py にDB系関数を追記した想定）
from module.utils.notion_utils import (
    notion_enabled,
    create_db_row,
    update_page_cover,
    append_heading,
    append_image,
    create_toggle_block,
    append_images_to_block,
)

# --------- 設定 ---------
BASE_URL = "https://www.weathercaster.jp/web/member_only/tenkizu"
PDF_FILES = [
    "COMP12.pdf", "COMP36.pdf", "COMP72.pdf",
    "FXXN519.pdf", "FZCX50.pdf", "FXJP854.pdf", "FEFE19.pdf",
    "TKAISETU.pdf", "SKAISETU.pdf",
    "AUPA20.pdf", "AUPN30.pdf", "AXJP140.pdf",
]

USER = os.environ.get("WEATHERCASTER_USER", "").strip()
PASS = os.environ.get("WEATHERCASTER_PASS", "").strip()

DATA_DIR = "/tmp/jma_data"
OUTPUT_DIR = "/tmp/weathercaster_jma"

# 変換/送付オプション
ATTACH_ALL_PAGES = os.environ.get("MAIL_ATTACH_ALL_PAGES", "0") == "1"  # JPG添付時：全ページ
JPEG_DPI = int(os.environ.get("JPEG_DPI", "200"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "85"))

# Notion / R2
R2_ENABLE = os.environ.get("R2_ENABLE", "1").lower() in ("1", "true", "yes", "on")
NOTION_DB_ID = os.environ.get("NOTION_DATABASE_ID", "").strip()

# Notion property names（上書き可能）
PROP_TITLE = os.environ.get("NOTION_PROP_TITLE", "名前")
PROP_MODEL = os.environ.get("NOTION_PROP_MODEL", "区分")
PROP_INITJST = os.environ.get("NOTION_PROP_INIT_JST", "初期時刻（JST）")
PROP_MEMO = os.environ.get("NOTION_PROP_MEMO", "メモ")
# optional
PROP_R2URL = os.environ.get("NOTION_PROP_R2URL", "R2 URL")
PROP_AUTOGEN = os.environ.get("NOTION_PROP_AUTOGEN", "自動生成")

# -----------------------

Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


def _now_jst_iso() -> str:
    """JSTの現在日時をISOで返す（Notion Dateにそのまま入れられる）"""
    # timezone(+09:00)
    jst = timezone.utc
    try:
        # 依存追加なしで +09:00 を作る
        jst = timezone(offset=timezone.utc.utcoffset(datetime.now()) or timezone.utc.utcoffset(datetime.now()))
    except Exception:
        pass
    # 上は環境によりズレる可能性があるので、固定+09:00を使用
    jst = timezone(offset=datetime.strptime("+0900", "%z").tzinfo.utcoffset(datetime.now()))
    return datetime.now(timezone.utc).astimezone(jst).isoformat()


def fetch_pdf_content(name: str) -> Optional[bytes]:
    """Basic認証でPDFを取得。失敗時 None"""
    url = f"{BASE_URL}/{name}"
    try:
        r = requests.get(url, auth=(USER, PASS), timeout=60)
        if r.status_code == 200:
            print(f"[OK] {name} downloaded")
            return r.content
        print(f"[NG] {name} HTTP {r.status_code}")
        return None
    except Exception as e:
        print(f"[ERR] {name} {e}")
        return None


def pdf_bytes_to_jpgs(
    pdf_bytes: bytes,
    base_filename: str,
    force_all: bool = False,
    simple_index: bool = False,
) -> List[Attachment]:
    """PDFをJPGへ。返り値は (filename, blob, mimetype) の配列"""
    images = convert_from_bytes(pdf_bytes, dpi=JPEG_DPI)
    if not images:
        return []

    atts: List[Attachment] = []

    # 全ページ添付（SKAISETUなど）
    if ATTACH_ALL_PAGES or force_all:
        for idx, im in enumerate(images, start=1):
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            fname = f"{base_filename}_{idx}.jpg" if simple_index else f"{base_filename}_p{idx:02d}.jpg"
            atts.append((fname, buf.getvalue(), "image/jpeg"))
        return atts

    # 1ページ目だけ添付
    buf = io.BytesIO()
    images[0].save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    atts.append((f"{base_filename}.jpg", buf.getvalue(), "image/jpeg"))
    return atts


def build_outputs(today: str) -> Tuple[List[Attachment], List[str]]:
    """全PDFをDL→JPG化。OUTPUT_DIR に書き出し、メール添付用配列も返す"""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    emails: List[Attachment] = []
    errors: List[str] = []

    if not USER or not PASS:
        errors.append("WEATHERCASTER_USER / PASS が未設定です")

    for name in PDF_FILES:
        pdf = fetch_pdf_content(name)
        if pdf is None:
            errors.append(f"{name}: download failed")
            continue

        base = f"{today}_{name.replace('.pdf', '')}"

        # SKAISETU は全ページ（簡易連番）／それ以外は1枚
        if name == "SKAISETU.pdf":
            imgs = pdf_bytes_to_jpgs(pdf, base, force_all=True, simple_index=True)
        else:
            imgs = pdf_bytes_to_jpgs(pdf, base, force_all=False, simple_index=False)

        if not imgs:
            errors.append(f"{name}: conversion produced no images")
            continue

        # 実ファイルとしても保存（デバッグ用）
        for fname, blob, _ in imgs:
            with open(os.path.join(OUTPUT_DIR, fname), "wb") as f:
                f.write(blob)

        emails.extend(imgs)

    return emails, errors


def upload_to_r2(today: str, atts: List[Attachment]) -> Tuple[List[str], Optional[str]]:
    """
    JPG をR2へアップし、公開URL一覧を返す。
    代表URL（先頭表示用）も返す。
    """
    if not R2_ENABLE:
        return [], None

    urls: List[str] = []
    rep_url: Optional[str] = None

    # 保存先：weathercaster/YYYYMMDD/...
    run_prefix = f"weathercaster/{today}"

    for (fname, blob, mime) in atts:
        key = f"{run_prefix}/{fname}"
        put_bytes(key, blob, content_type=mime)
        url = make_url(key)
        urls.append(url)
        if rep_url is None:
            rep_url = url

    return urls, rep_url


def notion_write_db(today: str, rep_url: Optional[str], all_urls: List[str], errors: List[str]) -> Optional[str]:
    """
    Notion DBに1行追加して、ページ本文に
    - 代表画像（page cover + 先頭にも1枚）
    - toggle内に全文画像
    を作る。
    """
    if (not notion_enabled()) or (not NOTION_DB_ID):
        return None

    # タイトル（DBの「名前」）
    title = f"Weathercaster 天気図 {today}"

    # 初期時刻（JST）：ここでは「実行した時刻」を入れる（あなたの運用に合わせてOK）
    init_jst = _now_jst_iso()

    props: Dict[str, Any] = {
        PROP_TITLE: {"title": [{"type": "text", "text": {"content": title}}]},
        PROP_MODEL: {"select": {"name": "Weathercaster"}},
        PROP_INITJST: {"date": {"start": init_jst}},
    }

    # メモ：エラー要約を入れておく（手書きで追記も可能）
    memo = ""
    if errors:
        memo = "ERROR:\n" + "\n".join(f"- {e}" for e in errors)
    if memo:
        props[PROP_MEMO] = {"rich_text": [{"type": "text", "text": {"content": memo[:1900]}}]}

    # 任意プロパティ：R2 URL / 自動生成
    # （DBに無い場合は Notion APIがエラーになるので、notion_utils側で握り潰すより「ここで入れない」方が安全。
    #  ただ、あなたのDBには作ってある前提なので入れておく）
    if all_urls:
        try:
            props[PROP_R2URL] = {"url": all_urls[0]}
        except Exception:
            pass
    try:
        props[PROP_AUTOGEN] = {"checkbox": True}
    except Exception:
        pass

    page_id = create_db_row(database_id=NOTION_DB_ID, properties=props, icon_emoji="🗺️")
    if not page_id:
        return None

    # cover（代表画像があれば）
    if rep_url:
        try:
            update_page_cover(page_id, rep_url)
        except Exception as e:
            print(f"[WARN] notion cover update failed: {e}")

    # 本文（代表1枚 + toggle）
    try:
        append_heading(page_id, "代表画像", level=3)
        if rep_url:
            append_image(page_id, rep_url)

        append_heading(page_id, "全文画像", level=3)
        toggle_id = create_toggle_block(page_id, "▼ 全文画像を開く")
        if toggle_id and all_urls:
            # toggle配下に画像を流し込む
            append_images_to_block(toggle_id, all_urls, chunk=30)

    except Exception as e:
        print(f"[WARN] notion body build failed: {e}")

    return page_id


def main():
    # 宛先（互換）
    mail_to = os.environ.get("MAIL_TO", os.environ.get("TO_EMAIL", "")).strip()

    # Slack通知モード（mail_utilsに渡す）
    #  "off" / "error_only" / "success"
    slack_mode = os.environ.get("SLACK_MODE", "success").strip()

    # 日付（UTC基準のままにするならこれ／JST基準にしたいならここを変更）
    today = datetime.utcnow().strftime("%Y%m%d")

    # 件名
    prefix = os.environ.get("MAIL_SUBJECT_PREFIX", "[JMA]").strip()
    subject = f"{prefix} Weathercaster 天気図 JPG {today}"

    try:
        emails, errors = build_outputs(today)

        # 件数を mail_utils 側に伝える（Slack表示の精度UP）
        os.environ["WX_ATTACH_COUNT"] = str(len(emails))
        os.environ["WX_ERROR_COUNT"] = str(len(errors))

        # 1) R2へアップ → URL化
        all_urls: List[str] = []
        rep_url: Optional[str] = None
        if emails and R2_ENABLE:
            try:
                all_urls, rep_url = upload_to_r2(today, emails)
                print(f"[OK] R2 uploaded: {len(all_urls)} files")
            except Exception as e:
                errors.append(f"R2 upload failed: {type(e).__name__}: {e}")
                print(f"[ERR] R2 upload failed: {e}")

        # 2) Notion DBへ記録（代表＋toggle）
        if all_urls and notion_enabled() and NOTION_DB_ID:
            try:
                page_id = notion_write_db(today, rep_url, all_urls, errors)
                print(f"[OK] Notion DB row created: {page_id}")
            except Exception as e:
                errors.append(f"Notion write failed: {type(e).__name__}: {e}")
                print(f"[ERR] Notion write failed: {e}")

        # 3) メール送信（ZIPにしない＝個別添付）
        if mail_to:
            body = (
                "Weathercasterの天気図をJPG化して添付します（保存なし運用）。\n"
                + (f"\nR2: {rep_url}\n" if rep_url else "")
                + ("\n".join(f"- ERROR: {e}" for e in errors) if errors else "")
            )

            msg_id = send_mail(
                to_addrs=mail_to,
                subject=subject,
                body=body,
                attachment_blobs=emails,      # ← 個別添付
                slack_mode=slack_mode,        # ← Slackは mail_utils に集約
            )
            print(f"[OK] Mail sent. Message-ID: {msg_id}")
        else:
            print("[WARN] MAIL_TO/TO_EMAIL が未設定のためメール送信をスキップしました。")

    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
