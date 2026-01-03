# -*- coding: utf-8 -*-
# =============================================================================
# scripts/adv_jma.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」を
# GitHub Actions 上で自動取得し、モデル別にメール送信する。
#
# ✅ 仕様（あなたの希望に合わせた）
# - 取得元は JMA tgv (GSM/MSM/LFM) のPNG
# - メール添付は JPG（PNGより軽くしたい）
# - GSM / MSM / LFM それぞれ「別メール」で送信（合計3通）
# - INITは固定値にせず「サイトに存在する時刻」を自動探索して合わせる
# - FT（予報時刻）を回して複数枚取得
#   * まずGSMから拡張していく運用に対応（環境変数でFT拡張を制御可能）
# - 失敗(401/403/404など)はSlackに要点ログを送る（設定があれば）
#
# ✅ 認証（重要）
# 優先順位：
#   1) JMA_ADV_USER / JMA_ADV_PASS から Authorization: Basic を生成（推奨）
#   2) JMA_AUTH_BASIC をそのまま利用（フォールバック）
#
# ✅ 依存
# - requests
# - pillow (PIL)  ← PNG→JPG変換
# - module.utils.mail_utils.send_mail
# - module.utils.slack_utils.send_slack_text
# =============================================================================

# --- GitHub Actions / 直叩き実行でも module/ を import できるようにする ---
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]  # scripts/ の1つ上 = リポジトリ直下
sys.path.insert(0, str(REPO_ROOT))
# -----------------------------------------------------------------------------


import os
import io
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
from PIL import Image

from module.utils.mail_utils import send_mail
from module.utils.slack_utils import send_slack_text


# =============================================================================
# 環境変数ユーティリティ
# =============================================================================
def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


# =============================================================================
# 認証：Authorization: Basic ...
# =============================================================================
def make_basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic() -> str:
    """
    優先順位：
      1) JMA_ADV_USER / JMA_ADV_PASS から生成（推奨）
      2) JMA_AUTH_BASIC をそのまま利用（フォールバック）
    """
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return make_basic_auth(user.strip(), pw.strip())

    return must_env("JMA_AUTH_BASIC").strip()


# =============================================================================
# Slack通知（設定があれば送る）
# =============================================================================
def slack_enabled() -> bool:
    return bool(os.getenv("SLACK_BOT_TOKEN")) and bool(os.getenv("SLACK_CHANNEL_ID"))


def slack_notify(text: str) -> None:
    if not slack_enabled():
        return
    try:
        channel = os.getenv("SLACK_CHANNEL_ID", "")
        send_slack_text(channel=channel, message=text)
    except Exception as e:
        print(f"[WARN] Slack notify failed: {e}")


# =============================================================================
# HTTPヘッダ（Safari互換寄り）
# =============================================================================
def headers_for(url: str, referer: str) -> dict:
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


# =============================================================================
# JPG変換（PNG bytes -> JPG bytes）
# =============================================================================
def png_bytes_to_jpg_bytes(png_bytes: bytes, *, quality: int = 85) -> bytes:
    """
    PNGをJPGに変換してサイズを抑える。
    - optimize=True で軽くなることが多い
    - progressive=True も軽量化に寄与することがある
    """
    with Image.open(io.BytesIO(png_bytes)) as im:
        # PNGがRGBAの場合、JPEGは透過不可なので白背景に合成
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
# URL組み立て
# =============================================================================
def fmt_rjtd(dt_utc: datetime) -> str:
    """
    RJTD用：MMDDHHMM
    ※ここが崩れると404祭りになります。分は必ず 00 に丸めます。
    """
    dt_utc = dt_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt_utc.strftime("%m%d%H%M")


def floor_to_step(dt_utc: datetime, step_hours: int) -> datetime:
    """
    UTC時刻を step_hours 単位で下方丸め（分は00固定）
    GSMは3h刻み、MSM/LFMは1h刻み…などに使う
    """
    dt_utc = dt_utc.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    h = (dt_utc.hour // step_hours) * step_hours
    return dt_utc.replace(hour=h)


def build_png_url(base: str, layer: str, view_code: str, rjtd: str) -> str:
    """
    例：
    https://www.jma.go.jp/bosai/tgv/data/GSMWide/300/images/VIEW3002000_RJTD_030600.png
    """
    return f"{base}/{layer}/images/VIEW{view_code}_RJTD_{rjtd}.png"


# =============================================================================
# モデル定義（あなたが貼ってくれたURL群を“構造化”）
# =============================================================================
@dataclass
class Item:
    label: str
    layer: str
    view_candidates: List[str]
    jpg_prefix: str


@dataclass
class ModelCfg:
    base: str
    referer: str
    ft_step_hours: int
    ft_list: List[int]
    items: List[Item]


def env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


def build_ft_list(max_ft: int, step: int) -> List[int]:
    """
    0..max_ft を step刻みで（max_ftを超えない）
    例：max_ft=27, step=3 -> 0,3,6,...,27
    """
    if max_ft < 0:
        return [0]
    out = list(range(0, max_ft + 1, step))
    if out[-1] != max_ft and max_ft % step != 0:
        # 端数を無理に入れない（ファイルがない確率が上がる）
        pass
    return out


def load_model_groups() -> Dict[str, ModelCfg]:
    """
    GSM→MSM→LFM の順でFT拡張できるように、最大FT/刻みを env で調整。
    ※ RJTD は UTC 前提。INIT探索ロジック側も必ず utcnow() を使うこと。
    """
    gsm_max  = env_int("GSM_MAX_FT", 27)   # 0..27h（3h刻み）
    gsm_step = env_int("GSM_FT_STEP", 3)

    msm_max  = env_int("MSM_MAX_FT", 0)    # まずは init のみ
    msm_step = env_int("MSM_FT_STEP", 1)

    lfm_max  = env_int("LFM_MAX_FT", 0)    # まずは init のみ
    lfm_step = env_int("LFM_FT_STEP", 1)

    groups: Dict[str, ModelCfg] = {
        "GSM": ModelCfg(
            base="https://www.jma.go.jp/bosai/tgv/data/GSMWide",
            referer="https://www.jma.go.jp/bosai/tgv/GSM/",
            # INIT探索・丸めに使う刻み（GSMは基本3h）
            init_step_hours=gsm_step,
            # 予想時刻(Forecast Time)の刻み
            ft_step_hours=gsm_step,
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
            ft_step_hours=msm_step,
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
            ft_step_hours=lfm_step,
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
    return groups



# =============================================================================
# INIT 自動探索（ここが “全404” を潰す心臓部）
# =============================================================================
def find_working_init_dt(model_name: str, cfg: ModelCfg, *, max_back_hours: int = 72) -> datetime:
    """
    いまのUTCから遡って、「ft=0の代表画像が200になる init_dt」を探す。
    - GSMは3h刻みで遡る（ft_step_hours=3）
    - MSM/LFMは1h刻みで遡る（ft_step_hours=1）

    これにより、JST/UTCズレや minutes混入で “全部404” を回避できる。
    """
    step = cfg.ft_step_hours
    now = datetime.now(timezone.utc)
    start = floor_to_step(now, step)

    # 代表1枚：items[0] の view_candidates[0]
    it0 = cfg.items[0]
    layer0 = it0.layer
    view0 = it0.view_candidates[0]

    for back in range(0, max_back_hours + 1, step):
        init_dt = start - timedelta(hours=back)
        rjtd = fmt_rjtd(init_dt)  # ft=0想定
        test_url = build_png_url(cfg.base, layer0, view0, rjtd)

        try:
            r = requests.get(test_url, headers=headers_for(test_url, cfg.referer), timeout=25)
            if r.status_code == 200:
                print(f"[OK] {model_name} init found: {init_dt.isoformat()} (RJTD_{rjtd})")
                return init_dt

            # 認証系は即終了（探しても無駄）
            if r.status_code in (401, 403):
                raise RuntimeError(f"{model_name} auth error HTTP {r.status_code} at {test_url}")

            print(f"[NG] {model_name} init RJTD_{rjtd} HTTP {r.status_code}")

        except Exception as e:
            # ネットワーク例外など
            print(f"[ERR] {model_name} init probe failed: {type(e).__name__}: {e}")

    raise RuntimeError(f"{model_name}: init not found within back={max_back_hours}h")


# =============================================================================
# 画像取得（PNG取得→JPG化して attachment_blobs を返す）
# =============================================================================
Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


def fetch_png(url: str, referer: str) -> Tuple[int, bytes, str]:
    """
    PNGを取得する（成功なら status=200）
    戻り値：(status_code, content_bytes, content_type)
    """
    r = requests.get(url, headers=headers_for(url, referer), timeout=40)
    ctype = (r.headers.get("Content-Type") or "").lower()
    return r.status_code, r.content, ctype


def run_model(model_name: str, cfg: ModelCfg, init_dt: datetime) -> Tuple[List[Attachment], List[str]]:
    """
    1モデル分を回して取得する。
    成功：attachment_blobs（JPGの個別添付用）
    失敗：errors（Slack用ログ）
    """
    jpg_quality = env_int("JPG_QUALITY", 85)

    attachments: List[Attachment] = []
    errors: List[str] = []

    for it in cfg.items:
        for ft in cfg.ft_list:
            # FTで時刻を進める（UTC、分=00固定）
            target_dt = init_dt + timedelta(hours=ft)
            rjtd = fmt_rjtd(target_dt)

            # view code は候補を順に試す（200/201揺れ対策）
            ok = False
            last_status = None

            for view_code in it.view_candidates:
                url = build_png_url(cfg.base, it.layer, view_code, rjtd)

                try:
                    status, content, ctype = fetch_png(url, cfg.referer)
                    last_status = status

                    if status == 200:
                        # HTMLが返ってくる事故（=認証ページ等）を軽く検知
                        if "text/html" in (ctype or "") or content[:20].lower().startswith(b"<!doctype html"):
                            errors.append(f"[{model_name}] {it.label} ft={ft}: got HTML (auth?) url={url}")
                            ok = False
                            break

                        # PNG→JPG
                        jpg = png_bytes_to_jpg_bytes(content, quality=jpg_quality)

                        # ファイル名（並べ替えしやすい：model_layer_ft）
                        fname = f"{it.jpg_prefix}_ft{ft:03d}.jpg"
                        attachments.append((fname, jpg, "image/jpeg"))
                        ok = True
                        print(f"[OK] {model_name} {it.label} ft={ft} -> {fname}")
                        break

                    # 認証系は即止め（候補viewを変えても意味がない）
                    if status in (401, 403):
                        errors.append(f"[{model_name}] {it.label} ft={ft}: HTTP{status} auth/forbidden url={url}")
                        ok = False
                        break

                    # 404は「まだ無い」可能性があるので次候補へ
                    if status == 404:
                        # 次の view_code へ
                        continue

                    # その他ステータスはログ
                    errors.append(f"[{model_name}] {it.label} ft={ft}: HTTP{status} url={url}")

                except Exception as e:
                    errors.append(f"[{model_name}] {it.label} ft={ft}: {type(e).__name__}: {e} url={url}")

            if not ok:
                # view候補を全部試してダメだった場合（404が多いはず）
                if last_status is None:
                    errors.append(f"[{model_name}] {it.label} ft={ft}: no response (network?)")
                else:
                    errors.append(f"[{model_name}] {it.label} ft={ft}: failed (last HTTP{last_status})")

    return attachments, errors


# =============================================================================
# メール送信（モデルごとに1通）
# =============================================================================
def send_model_mail(model_name: str, init_dt: datetime, atts: List[Attachment], errors: List[str]) -> None:
    """
    mail_utils.send_mail を使って、JPGを個別添付で送る。
    587=STARTTLS は mail_utils 側が対応している（あなたの運用と揃う）。
    """
    # 宛先は mail_utils が TO_EMAIL / FROM_EMAIL / SMTP_* を参照
    prefix = os.getenv("MAIL_SUBJECT_PREFIX", "JMA").strip()
    init_str = init_dt.strftime("%m/%d %H:00(UTC)")
    subject = f"{prefix} ADV TGV {model_name} init={init_str}"

    body_lines = [
        f"JMA 防災情報アドバイザー向け 専門天気図（tgv）: {model_name}",
        f"init: {init_str}",
        "",
        f"files: {len(atts)}",
        f"errors: {len(errors)}",
        "",
        "※ 個人利用・非公開",
        "※ GitHub Actions 実行",
    ]
    body = "\n".join(body_lines)

    # 個別JPG添付で送る
    send_mail(
        subject=subject,
        body=body,
        attachment_blobs=atts,
        is_html=False,
        slack_mode="off",  # Slackはこのスクリプト側で “401/404ログ” を投げる
    )

    print(f"[OK] {model_name} mail sent: files={len(atts)} errors={len(errors)}")


# =============================================================================
# main（3モデルを順に回して “3通送る”）
# =============================================================================
def main() -> None:
    print("=== Start ADV JMA TGV ===")

    groups = load_model_groups()

    # モデルごとに init を探して回す（GSM/MSM/LFMは更新間隔が違う可能性があるため別探索）
    for model_name in ("GSM", "MSM", "LFM"):
        cfg = groups[model_name]
        print(f"\n--- Fetch group: {model_name} ({len(cfg.items)} items) ---")

        # INIT探索
        try:
            init_dt = find_working_init_dt(model_name, cfg, max_back_hours=72)
        except Exception as e:
            msg = f"❌ ADV TGV {model_name}: INIT not found / auth error\n{type(e).__name__}: {e}"
            print(msg)
            slack_notify(msg)
            # ここで止めるか、次モデルへ行くか：運用上は “次へ” が便利
            continue

        # 取得
        atts, errors = run_model(model_name, cfg, init_dt)

        # 取得ゼロは致命的：Slackへ（メールは送らない）
        if not atts:
            msg = (
                f"❌ ADV TGV {model_name}: no images fetched\n"
                f"init={init_dt.isoformat()}\n"
                + ("\n".join(errors[:30]) if errors else "(no detail)")
            )
            print(msg)
            slack_notify(msg)
            continue

        # エラーがあればSlackへ（401/403/404の要点だけで十分）
        if errors:
            # 長すぎるとSlackが辛いので上位だけ
            msg = (
                f"⚠️ ADV TGV {model_name}: fetch errors ({len(errors)})\n"
                f"init={init_dt.strftime('%m/%d %H:00(UTC)')}\n"
                + "\n".join(errors[:40])
            )
            slack_notify(msg)

        # メール送信（モデルごとに1通）
        try:
            send_model_mail(model_name, init_dt, atts, errors)
        except Exception as e:
            msg = f"❌ ADV TGV {model_name}: mail send failed\n{type(e).__name__}: {e}"
            print(msg)
            slack_notify(msg)

    print("\n=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
