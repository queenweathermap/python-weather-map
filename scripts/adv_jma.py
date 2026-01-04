# scripts/adv_jma.py
# -*- coding: utf-8 -*-
# =============================================================================
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」を自動取得し、
# “天気図ごと（itemごと）” に Slack投稿（画像添付）またはメール送信する。
#
# ✅ 仕様（最終要望対応）
# - 取得元：JMA tgv の PNG
# - 配送：JPG（PNG→JPG変換して軽量化）
# - “天気図ごと（itemごと）” に分割して送る（アニメ確認しやすい）
# - INIT（RJTD）は「存在する初期時刻」を自動探索して合わせる
# - FT は VIEWコード末尾で表現（RJTDは init 固定） ← 重要（404祭り回避）
# - Slack通知：404は出さない
#   * 401/403（認証系） or モデル全滅（1枚も取れない）だけ通知
#
# ✅ 認証（優先順位）
#   1) JMA_ADV_USER / JMA_ADV_PASS → Basic生成（推奨）
#   2) JMA_AUTH_BASIC → "Basic xxxx" をそのまま利用（フォールバック）
#
# ✅ 配送モード（環境変数）
# - DELIVERY_MODE: "slack" / "email" / "both"（default="slack"）
# - SLACK_CHUNK:   1投稿あたりの添付数（default=10）
#
# ✅ 依存
# - requests
# - pillow
# - module.utils.slack_utils.upload_bytes_slack, send_slack_text
# - module.utils.mail_utils.send_mail（email/both時のみ）
# =============================================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import os
import io
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional

import requests
from PIL import Image

from module.utils.slack_utils import send_slack_text, upload_bytes_slack

# email/both のときだけ使う（import自体はOK）
from module.utils.mail_utils import send_mail


# =============================================================================
# Types
# =============================================================================
Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


# =============================================================================
# Env
# =============================================================================
def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


def env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return default if (v is None or v.strip() == "") else v.strip()


# =============================================================================
# Auth
# =============================================================================
def make_basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic() -> str:
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return make_basic_auth(user.strip(), pw.strip())
    return must_env("JMA_AUTH_BASIC").strip()


# =============================================================================
# Slack (notify only for important cases)
# =============================================================================
def slack_enabled() -> bool:
    return bool(os.getenv("SLACK_BOT_TOKEN")) and bool(os.getenv("SLACK_CHANNEL_ID"))


def slack_notify(text: str) -> None:
    """
    重要通知のみで使う（401/403 / モデル全滅 / 配送失敗 など）
    """
    if not slack_enabled():
        return
    try:
        channel = os.getenv("SLACK_CHANNEL_ID", "").strip()
        if not channel:
            return
        # send_slack_text(channel, message) なので keyword は使わない
        send_slack_text(channel, text)
    except Exception as e:
        print(f"[WARN] Slack notify failed: {e}")


def send_item_slack(
    model_name: str,
    item_label: str,
    init_dt: datetime,
    atts: List[Attachment],
    *,
    chunk_size: int = 10,
) -> None:
    """
    天気図（item）ごとに Slack へ投稿。
    - 画像は10枚ずつ等に分割（Slack制限・閲覧性対策）
    """
    channel = os.getenv("SLACK_CHANNEL_ID", "").strip()
    if not channel:
        raise RuntimeError("SLACK_CHANNEL_ID is missing")

    init_str = init_dt.strftime("%m/%d %H:00(UTC)")
    header = f"🗺️ ADV TGV {model_name} {item_label}  init={init_str}  files={len(atts)}"

    # (filename, jpg_bytes, mime) -> (filename, bytes)
    pairs: List[Tuple[str, bytes]] = [(fn, blob) for (fn, blob, _mime) in atts]

    for i in range(0, len(pairs), chunk_size):
        chunk = pairs[i:i + chunk_size]
        if i == 0:
            comment = header
        else:
            comment = f"🗺️ ADV TGV {model_name} {item_label}（続き {i//chunk_size + 1}）"
        upload_bytes_slack(channel=channel, files=chunk, initial_comment=comment)

    print(f"[OK] slack sent: {model_name} {item_label} files={len(atts)}")


# =============================================================================
# HTTP
# =============================================================================
def headers_for(referer: str) -> dict:
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


# =============================================================================
# PNG -> JPG
# =============================================================================
def png_bytes_to_jpg_bytes(png_bytes: bytes, *, quality: int = 85) -> bytes:
    with Image.open(io.BytesIO(png_bytes)) as im:
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im2 = bg
        else:
            im2 = im.convert("RGB")

        out = io.BytesIO()
        im2.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()


# =============================================================================
# URL rules
# =============================================================================
def fmt_rjtd(init_dt_utc: datetime) -> str:
    """
    RJTD: MMDDHHMM (UTC) / 分は必ず00
    """
    dt = init_dt_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt.strftime("%m%d%H%M")


def floor_to_step(dt_utc: datetime, step_hours: int) -> datetime:
    dt = dt_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    h = (dt.hour // step_hours) * step_hours
    return dt.replace(hour=h)


def build_png_url(base: str, layer: str, view_code: str, rjtd: str) -> str:
    return f"{base}/{layer}/images/VIEW{view_code}_RJTD_{rjtd}.png"


def view_for_ft(view_base: str, ft_hours: int) -> str:
    """
    ✅ 重要：FTはVIEWコード末尾で表現する（RJTDはinit固定）

    - GSM例：3102000(ft=0) → 3102003(ft=3) → 3102006(ft=6)
      → view_baseが7桁以上なら末尾3桁を ft に差し替える

    - MSM/LFM例：500200(ft=0) → 500201(ft=1) → ... → 500227(ft=27)
      → view_baseが6桁程度なら末尾2桁を ft に差し替える
    """
    digits = 3 if len(view_base) >= 7 else 2
    return f"{view_base[:-digits]}{ft_hours:0{digits}d}"


# =============================================================================
# Model configs
# =============================================================================
@dataclass
class Item:
    label: str
    layer: str
    view_candidates: List[str]   # “系列”候補（末尾FTは view_for_ft() が上書き）
    jpg_prefix: str


@dataclass
class ModelCfg:
    base: str
    referer: str
    init_step_hours: int         # init探索の刻み（GSM=3, MSM/LFM=1）
    ft_list: List[int]
    items: List[Item]


def build_ft_list(max_ft: int, step: int) -> List[int]:
    if max_ft < 0:
        return [0]
    return list(range(0, max_ft + 1, step))


def load_model_groups() -> Dict[str, ModelCfg]:
    """
    “GSMから拡張→MSM拡張→LFM拡張” に対応
    - GSM_MAX_FT (default=27) / GSM_FT_STEP (default=3)
    - MSM_MAX_FT (default=0)  / MSM_FT_STEP (default=1)
    - LFM_MAX_FT (default=0)  / LFM_FT_STEP (default=1)
    """
    gsm_max  = env_int("GSM_MAX_FT", 27)
    gsm_step = env_int("GSM_FT_STEP", 3)

    msm_max  = env_int("MSM_MAX_FT", 0)
    msm_step = env_int("MSM_FT_STEP", 1)

    lfm_max  = env_int("LFM_MAX_FT", 0)
    lfm_step = env_int("LFM_FT_STEP", 1)

    return {
        "GSM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/GSMWide",
            referer="https://www.jma.go.jp/bosai/tgv/GSM/",
            init_step_hours=3,
            ft_list=build_ft_list(gsm_max, gsm_step),
            items=[
                Item(label="300hPa",   layer="300",  view_candidates=["3002000"], jpg_prefix="GSM_300"),
                Item(label="300hPa-2", layer="3002", view_candidates=["3102000"], jpg_prefix="GSM_3002"),
            ],
        ),
        "MSM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/MSMNarrow",
            referer="https://www.jma.go.jp/bosai/tgv/MSM/",
            init_step_hours=1,
            ft_list=build_ft_list(msm_max, msm_step),
            items=[
                Item(label="500hPa",   layer="500",  view_candidates=["500200"], jpg_prefix="MSM_500"),
                Item(label="500hPa-2", layer="5002", view_candidates=["510200"], jpg_prefix="MSM_5002"),
                Item(label="700hPa",   layer="700",  view_candidates=["700200"], jpg_prefix="MSM_700"),
            ],
        ),
        "LFM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/LFMNarrow",
            referer="https://www.jma.go.jp/bosai/tgv/LFM/",
            init_step_hours=1,
            ft_list=build_ft_list(lfm_max, lfm_step),
            items=[
                Item(label="850hPa",   layer="850",  view_candidates=["850200", "850201"], jpg_prefix="LFM_850"),
                Item(label="850hPa-2", layer="8502", view_candidates=["860200", "860201"], jpg_prefix="LFM_8502"),
                Item(label="925hPa",   layer="925",  view_candidates=["920200", "920201"], jpg_prefix="LFM_925"),
                Item(label="975hPa",   layer="975",  view_candidates=["970200", "970201"], jpg_prefix="LFM_975"),
                Item(label="sfc",      layer="sfc",  view_candidates=["000200", "000201"], jpg_prefix="LFM_sfc"),
                Item(label="sfc-2",    layer="sfc2", view_candidates=["010200", "010201"], jpg_prefix="LFM_sfc2"),
            ],
        ),
    }


# =============================================================================
# INIT auto-detect
# =============================================================================
def probe_url_status(url: str, referer: str) -> int:
    r = requests.get(url, headers=headers_for(referer), timeout=25)
    return r.status_code


def find_working_init_dt(model_name: str, cfg: ModelCfg, *, max_back_hours: int = 72) -> datetime:
    """
    今のUTCから遡って、「ft=0 の代表画像が 200 になる init_dt」を探す。
    - GSMは3h刻みで遡る
    - MSM/LFMは1h刻みで遡る
    """
    step = cfg.init_step_hours
    now = datetime.now(timezone.utc)
    start = floor_to_step(now, step)

    it0 = cfg.items[0]
    base_view = it0.view_candidates[0]
    view0 = view_for_ft(base_view, 0)  # ft=0
    layer0 = it0.layer

    for back in range(0, max_back_hours + 1, step):
        init_dt = start - timedelta(hours=back)
        rjtd = fmt_rjtd(init_dt)
        url = build_png_url(cfg.base, layer0, view0, rjtd)

        try:
            st = probe_url_status(url, cfg.referer)
            if st == 200:
                print(f"[OK] {model_name} init found: {init_dt.isoformat()} (RJTD_{rjtd}) url={url}")
                return init_dt

            if st in (401, 403):
                # ここは重要：Slack通知対象
                raise RuntimeError(f"{model_name} auth error HTTP{st} url={url}")

            # 404等は探索継続（Slackには出さない）
            print(f"[NG] {model_name} init RJTD_{rjtd} HTTP{st} url={url}")

        except Exception as e:
            print(f"[ERR] {model_name} init probe failed: {type(e).__name__}: {e}")

    raise RuntimeError(f"{model_name}: init not found within back={max_back_hours}h")


# =============================================================================
# Fetch per-item
# =============================================================================
def fetch_png(url: str, referer: str) -> Tuple[int, bytes, str]:
    r = requests.get(url, headers=headers_for(referer), timeout=40)
    ctype = (r.headers.get("Content-Type") or "").lower()
    return r.status_code, r.content, ctype


def fetch_item_images(model_name: str, cfg: ModelCfg, init_dt: datetime, item: Item) -> Tuple[List[Attachment], bool]:
    """
    1アイテム（=天気図）ぶん取得
    戻り値：
      - attachments: JPG添付リスト
      - auth_failed: 401/403 または HTML（認証ページっぽい）が出たら True（Slack対象）
    """
    jpg_quality = env_int("JPG_QUALITY", 85)
    rjtd = fmt_rjtd(init_dt)  # ✅ RJTDはinit固定

    atts: List[Attachment] = []
    auth_failed = False

    for ft in cfg.ft_list:
        got_one = False

        for base_view in item.view_candidates:
            view_code = view_for_ft(base_view, ft)
            url = build_png_url(cfg.base, item.layer, view_code, rjtd)

            try:
                status, content, ctype = fetch_png(url, cfg.referer)

                if status == 200:
                    # HTMLが返る事故（認証ページ等）
                    if "text/html" in ctype or content[:20].lower().startswith(b"<!doctype html"):
                        auth_failed = True
                        print(f"[NG] {model_name} {item.label} ft={ft}: got HTML (auth?) url={url}")
                        got_one = False
                        break

                    jpg = png_bytes_to_jpg_bytes(content, quality=jpg_quality)
                    fname = f"{item.jpg_prefix}_ft{ft:03d}.jpg"
                    atts.append((fname, jpg, "image/jpeg"))
                    print(f"[OK] {model_name} {item.label} ft={ft} url={url}")
                    got_one = True
                    break

                if status in (401, 403):
                    auth_failed = True
                    print(f"[NG] {model_name} {item.label} ft={ft}: HTTP{status} auth url={url}")
                    got_one = False
                    break

                # ✅ 404は “あるある” → Slackに出さない（printのみ）
                if status == 404:
                    print(f"[NG] {model_name} {item.label} ft={ft}: HTTP404 url={url}")
                    continue

                print(f"[NG] {model_name} {item.label} ft={ft}: HTTP{status} url={url}")

            except Exception as e:
                # ネットワーク例外も Slackには出さない（モデル全滅時にまとめて通知）
                print(f"[ERR] {model_name} {item.label} ft={ft}: {type(e).__name__}: {e} url={url}")

        if auth_failed:
            # auth疑いが出たら打ち切り
            break

        # got_one が False でも継続（ftごとに無いことはある）
        _ = got_one

    return atts, auth_failed


def send_item_mail(model_name: str, item: Item, init_dt: datetime, atts: List[Attachment]) -> None:
    prefix = env_str("MAIL_SUBJECT_PREFIX", "JMA")
    init_str = init_dt.strftime("%m/%d %H:00(UTC)")
    subject = f"{prefix} ADV TGV {model_name} {item.label} init={init_str}"

    body = "\n".join([
        "JMA 防災情報アドバイザー向け 専門天気図（tgv）",
        f"model: {model_name}",
        f"chart: {item.label}",
        f"init : {init_str}",
        f"files: {len(atts)}",
        "",
        "※ 個人利用・非公開",
        "※ GitHub Actions 実行",
    ])

    send_mail(
        subject=subject,
        body=body,
        attachment_blobs=atts,  # JPG 個別添付
        is_html=False,
        slack_mode="off",
    )
    print(f"[OK] mail sent: {model_name} {item.label} files={len(atts)}")


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start ADV JMA TGV ===")

    delivery_mode = env_str("DELIVERY_MODE", "slack").lower()  # slack/email/both
    chunk_size = env_int("SLACK_CHUNK", 10)

    groups = load_model_groups()

    for model_name in ("GSM", "MSM", "LFM"):
        cfg = groups[model_name]
        print(f"\n--- Fetch model: {model_name} items={len(cfg.items)} ---")

        # 1) init探索
        try:
            init_dt = find_working_init_dt(model_name, cfg, max_back_hours=72)
        except Exception as e:
            msg = f"❌ ADV TGV {model_name}: INIT not found / auth error\n{type(e).__name__}: {e}"
            print(msg)
            slack_notify(msg)  # ✅ 重要通知
            continue

        total_files_model = 0
        auth_failed_model = False

        # 2) itemごとに取得 → 配送
        for item in cfg.items:
            atts, auth_failed = fetch_item_images(model_name, cfg, init_dt, item)

            if auth_failed:
                auth_failed_model = True
                break

            if not atts:
                # ✅ item単位の全滅はSlackしない（よくあるため）
                print(f"[WARN] {model_name} {item.label}: no files (maybe 404s)")
                continue

            total_files_model += len(atts)

            # Slack / Email / Both（itemごと）
            try:
                if delivery_mode in ("slack", "both"):
                    send_item_slack(model_name, item.label, init_dt, atts, chunk_size=chunk_size)
                if delivery_mode in ("email", "both"):
                    send_item_mail(model_name, item, init_dt, atts)
            except Exception as e:
                # 配送失敗は重要通知
                msg = f"❌ ADV TGV {model_name} {item.label}: delivery failed\n{type(e).__name__}: {e}"
                print(msg)
                slack_notify(msg)

        # 3) Slack通知条件（希望どおり）
        if auth_failed_model:
            msg = f"❌ ADV TGV {model_name}: auth error (401/403 or HTML detected)."
            print(msg)
            slack_notify(msg)
            continue

        if total_files_model == 0:
            # ✅ モデル全滅のみSlack
            msg = (
                f"❌ ADV TGV {model_name}: no images fetched (model total=0)\n"
                f"init={init_dt.strftime('%m/%d %H:00(UTC)')}"
            )
            print(msg)
            slack_notify(msg)

    print("\n=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
