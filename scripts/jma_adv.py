# -*- coding: utf-8 -*-
"""
scripts/jma_adv.py

JMA 防災情報アドバイザー向け「専門天気図（tgv）」を自動取得し、
“天気図ごと（itemごと）” にメール送信（必須）＋ Slack投稿（任意）＋ Notion登録（任意）する。

✅ 仕様（あなたの現行URL規則に準拠）
- FT は VIEWコード末尾で表現（RJTD は init 固定）
- GSM: FT=3..30 (3h) 10枚 / item
- MSM: FT=1..15(1h) + 18,21,24,27,30 合計20枚 / item
- LFM: FT=4..18(1h) 15枚 / item

環境変数（メールは必須）
- SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
- MAIL_FROM, MAIL_TO   (MAIL_TO はカンマ区切り可)
- MAIL_SUBJECT_PREFIX (任意)

R2（任意）
- R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
- R2_PUBLIC_BASE_URL (任意：カスタムドメイン運用推奨)

Slack（任意）
- SLACK_WEBHOOK_URL
- SLACK_POST_IMAGES (1/0) 画像も投げるか（デフォルト: 1）
- SLACK_POST_ERRORS (1/0) エラーのみ（デフォルト: 1）

Notion（任意）
- NOTION_TOKEN, NOTION_DATABASE_ID
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import smtplib
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# --- import path fix (GitHub Actions / local both) -----------------
# scripts/ 配下のスクリプトを `python scripts/jma_adv.py` で実行しても
# `from scripts.xxx import ...` が通るように、プロジェクトルートを sys.path に追加する
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
# -------------------------------------------------------------------


# 同一リポジトリ想定
from scripts.r2_utils import upload_file_to_r2
from module.utils.notion_utils import create_weather_page, is_notion_enabled


# -------------------------
# 設定（ここをあなたの現行VIEWコードに揃える）
# -------------------------
@dataclass
class ItemSpec:
    name: str
    # ここが「FT以外が固定のVIEWコード本体」。
    # FTは末尾に付ける想定（あなたの規則に合わせる）
    view_base: str


# 例：ここをあなたの“現行URL規則のVIEWコード”に置換してください
# view_base は「末尾のFT部分を除いた形」を入れる
ITEMS: Dict[str, List[ItemSpec]] = {
    "GSM": [
        ItemSpec(name="item01", view_base="RJTD_INIT_GSM_ITEM01_FT"),
        ItemSpec(name="item02", view_base="RJTD_INIT_GSM_ITEM02_FT"),
    ],
    "MSM": [
        ItemSpec(name="item01", view_base="RJTD_INIT_MSM_ITEM01_FT"),
        ItemSpec(name="item02", view_base="RJTD_INIT_MSM_ITEM02_FT"),
    ],
    "LFM": [
        ItemSpec(name="item01", view_base="RJTD_INIT_LFM_ITEM01_FT"),
        ItemSpec(name="item02", view_base="RJTD_INIT_LFM_ITEM02_FT"),
    ],
}


def ft_list(model: str) -> List[int]:
    model = model.upper()
    if model == "GSM":
        return list(range(3, 31, 3))  # 3,6,...,30 (10枚)
    if model == "MSM":
        return list(range(1, 16)) + [18, 21, 24, 27, 30]  # 20枚
    if model == "LFM":
        return list(range(4, 19))  # 4..18 (15枚)
    raise ValueError(f"Unknown model: {model}")


def build_view_code(view_base: str, ft: int) -> str:
    """
    あなたの規則：VIEWコード末尾でFT表現
    例: {view_base}{ft:02d} のように。
    """
    return f"{view_base}{ft:02d}"


def build_tgv_url(view_code: str) -> str:
    """
    JMA TGV画像URL（あなたの運用URL規則に合わせてここを調整）
    例として /bosai/forecast/data/tgv/ を採用。

    ※すでにあなたのプロジェクトで「正しいURL」が決まっているはずなので、
      その形式に置換してください。
    """
    return f"https://www.jma.go.jp/bosai/forecast/data/tgv/{view_code}.png"


# -------------------------
# Slack（任意）
# -------------------------
def slack_enabled() -> bool:
    return bool(os.environ.get("SLACK_WEBHOOK_URL", "").strip())


def slack_post(text: str, *, webhook_url: Optional[str] = None) -> None:
    url = (webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")).strip()
    if not url:
        return
    requests.post(url, json={"text": text}, timeout=20).raise_for_status()


def env_flag(name: str, default: str = "1") -> bool:
    v = os.environ.get(name, default).strip().lower()
    return v in ("1", "true", "yes", "y", "on")


# -------------------------
# Mail（必須）
# -------------------------
@dataclass
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    mail_from: str
    mail_to: List[str]
    subject_prefix: str = ""


def load_smtp_config() -> SmtpConfig:
    host = os.environ.get("SMTP_HOST", "").strip()
    port_s = os.environ.get("SMTP_PORT", "587").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    mail_from = os.environ.get("MAIL_FROM", "").strip()
    mail_to_raw = os.environ.get("MAIL_TO", "").strip()
    subject_prefix = os.environ.get("MAIL_SUBJECT_PREFIX", "").strip()

    missing = []
    for k, v in [
        ("SMTP_HOST", host),
        ("SMTP_USER", user),
        ("SMTP_PASS", password),
        ("MAIL_FROM", mail_from),
        ("MAIL_TO", mail_to_raw),
    ]:
        if not v:
            missing.append(k)
    if missing:
        raise RuntimeError(f"Missing required env vars for SMTP: {', '.join(missing)}")

    try:
        port = int(port_s)
    except ValueError:
        raise RuntimeError("SMTP_PORT must be integer")

    mail_to = [x.strip() for x in mail_to_raw.split(",") if x.strip()]
    if not mail_to:
        raise RuntimeError("MAIL_TO is empty after parsing")

    return SmtpConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        mail_from=mail_from,
        mail_to=mail_to,
        subject_prefix=subject_prefix,
    )


def send_mail_with_attachments(
    *,
    subject: str,
    body: str,
    attachments: List[Tuple[str, bytes, str]],
) -> None:
    cfg = load_smtp_config()

    msg = EmailMessage()
    msg["From"] = cfg.mail_from
    msg["To"] = ", ".join(cfg.mail_to)
    msg["Subject"] = f"{cfg.subject_prefix}{subject}".strip()
    msg.set_content(body)

    for filename, content, mime_type in attachments:
        maintype, subtype = mime_type.split("/", 1)
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as s:
        s.starttls()
        s.login(cfg.user, cfg.password)
        s.send_message(msg)


# -------------------------
# Download
# -------------------------
def download_png(url: str, out_path: Path) -> None:
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    out_path.write_bytes(r.content)


def today_jst_iso() -> str:
    # GitHub Actions はUTC基準になりがちなので、JST基準の「日付」を作る
    jst = timezone.utc
    # ここでは「実行時UTC」を使い、必要なら運用でJST補正してください。
    # （厳密にJST日付で回すなら、workflow側でTZ=Asia/Tokyoにするのが確実）
    return datetime.now(jst).date().isoformat()


# -------------------------
# Main
# -------------------------
def main() -> int:
    run_date = os.environ.get("RUN_DATE", "").strip() or today_jst_iso()
    enable_r2 = bool(os.environ.get("R2_ACCOUNT_ID", "").strip())
    enable_notion = is_notion_enabled()
    enable_slack = slack_enabled()
    slack_post_images = env_flag("SLACK_POST_IMAGES", "1")
    slack_post_errors = env_flag("SLACK_POST_ERRORS", "1")

    errors: List[str] = []
    summary: Dict[str, Dict[str, int]] = {}

    base_tmp = Path(tempfile.mkdtemp(prefix="jma_adv_"))
    try:
        for model, items in ITEMS.items():
            model = model.upper()
            fts = ft_list(model)
            summary[model] = {}

            for item in items:
                ok_count = 0
                attachments: List[Tuple[str, bytes, str]] = []
                r2_urls: List[str] = []

                item_dir = base_tmp / model / item.name
                item_dir.mkdir(parents=True, exist_ok=True)

                for ft in fts:
                    view_code = build_view_code(item.view_base, ft)
                    url = build_tgv_url(view_code)
                    filename = f"{model}_{item.name}_ft{ft:02d}.png"
                    out_path = item_dir / filename

                    try:
                        download_png(url, out_path)
                        content = out_path.read_bytes()
                        attachments.append((filename, content, "image/png"))
                        ok_count += 1

                        # R2へ（任意）
                        public_url = None
                        if enable_r2:
                            object_key = f"jma_adv/{run_date}/{model}/{item.name}/ft{ft:02d}.png"
                            public_url = upload_file_to_r2(str(out_path), object_key, content_type="image/png")
                            r2_urls.append(public_url)

                            # Notionへ（任意）
                            if enable_notion:
                                title = f"{run_date} {model} {item.name} ft{ft:02d}"
                                # Statusは1枚単位はok固定、必要なら後で拡張
                                create_weather_page(
                                    title=title,
                                    date_iso=run_date,
                                    model=model,
                                    item=item.name,
                                    ft=f"ft{ft:02d}",
                                    image_url=public_url,
                                    status="ok",
                                )

                    except Exception as e:
                        msg = f"[{model}/{item.name}/ft{ft:02d}] failed: {url} ({e})"
                        errors.append(msg)
                        if enable_slack and slack_post_errors:
                            try:
                                slack_post(f"⚠️ {msg}")
                            except Exception:
                                pass

                summary[model][item.name] = ok_count

                # メール（必須）：itemごとにまとめて送る
                subject = f"JMA ADV {run_date} {model} {item.name} ({ok_count}/{len(fts)})"
                lines = [
                    f"date: {run_date}",
                    f"model: {model}",
                    f"item : {item.name}",
                    f"count: {ok_count}/{len(fts)}",
                ]
                if enable_r2 and r2_urls:
                    lines.append("")
                    lines.append("R2 URLs (first 5):")
                    lines.extend(r2_urls[:5])
                    if len(r2_urls) > 5:
                        lines.append(f"... (+{len(r2_urls)-5} more)")

                body = "\n".join(lines)

                # 添付が0枚でも送るとノイズなので、0のときはエラー扱いで本文メールだけ送る
                if ok_count == 0:
                    body += "\n\nNo attachments downloaded. Please check VIEW codes / URL rule."
                    send_mail_with_attachments(subject=subject, body=body, attachments=[])
                else:
                    send_mail_with_attachments(subject=subject, body=body, attachments=attachments)

                # Slack（任意）：画像を投げない運用にも合わせる
                if enable_slack and slack_post_images:
                    try:
                        slack_post(f"✅ Sent: {subject}")
                    except Exception:
                        pass

        # 最後にサマリ
        if enable_slack:
            try:
                slack_post("📌 Summary\n" + json.dumps(summary, ensure_ascii=False, indent=2))
            except Exception:
                pass

        if errors:
            print("Errors:")
            print("\n".join(errors), file=sys.stderr)
            return 1

        print("OK")
        return 0

    finally:
        shutil.rmtree(base_tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(traceback.format_exc(), file=sys.stderr)
        # Slackに落とす（任意）
        if slack_enabled() and env_flag("SLACK_POST_ERRORS", "1"):
            try:
                slack_post("🔥 jma_adv.py crashed\n" + traceback.format_exc()[-1500:])
            except Exception:
                pass
        raise
