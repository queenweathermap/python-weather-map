# -*- coding: utf-8 -*-
# =============================================================================
# scripts/adv_jma.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」を取得して
#  1) GSM 1通
#  2) MSM 1通
#  3) LFM 1通
# の合計3通のメールで送る（JPG個別添付）。
#
# 【狙い】
# - Safari で観測した Authorization / Referer を再現して取得
# - init(イニシャル時刻)は固定せず、「最新で取得できるinit」を自動探索
# - FT=0(イニシャル)〜最大FTまで「各時」の画像を大量に取得
# - 取得したPNGは保存用に残さない（取得→JPG化→添付用bytes化）
# - 401/403/404など失敗や欠損は Slack にログを送る
#
# 【メール送信】
# - module.utils.mail_utils.send_mail を使う（587=STARTTLS対応）
# - JPGを個別添付（ZIPにしない）
#
# 【重要：認証】
# - 優先: JMA_ADV_USER / JMA_ADV_PASS から Basic を生成
# - 予備: JMA_AUTH_BASIC をそのまま使う（フォールバック）
#
# 【URL規則（観測ベース）】
# - ファイル名末尾 _DDHHMM は init 時刻（UTC）に見える（例: _030600 = 03日06UTC）
# - VIEWの末尾の数字が FT を表しているように見える
#   - GSM: VIEW3002 + 000/003/006/...（FTが3時間刻みで3桁）
#   - MSM/LFM: VIEW500 + 200/201/202/...（FTが1時間刻みで200+FT）
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
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
from PIL import Image  # pillow が必要（requirements.txt に pillow を入れてください）

from module.utils.mail_utils import send_mail
from module.utils.slack_utils import send_slack_text


# =============================================================================
# 0) 共通設定（環境変数）
# =============================================================================

# JPG品質（線画が多いので 85〜90 推奨。上げるほどサイズは増える）
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "88"))

# メールは「個別JPG添付」が基本（weathercaster と揃える）
# ※必要になったら ZIP にしたい…という将来の保険は残すなら "1" に切替可
MAIL_AS_ZIP = os.environ.get("MAIL_AS_ZIP", "0") == "1"

# 取得のタイムアウト/リトライ
HTTP_TIMEOUT_SEC = int(os.environ.get("HTTP_TIMEOUT_SEC", "30"))
HTTP_RETRY = int(os.environ.get("HTTP_RETRY", "3"))
HTTP_RETRY_WAIT_SEC = int(os.environ.get("HTTP_RETRY_WAIT_SEC", "10"))

# init探索の上限（何回ぶん過去へ遡って探すか）
INIT_PROBE_LIMIT = int(os.environ.get("INIT_PROBE_LIMIT", "24"))

# Slack通知（SLACK_* が無ければ何もしない）
SLACK_MODE = os.environ.get("SLACK_MODE", "error_only").strip()  # off / error_only / success


# =============================================================================
# 1) ユーティリティ
# =============================================================================

Attachment = Tuple[str, bytes, str]  # (filename, blob, mimetype)


def must_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def slack_enabled() -> bool:
    return bool(os.getenv("SLACK_BOT_TOKEN") and os.getenv("SLACK_CHANNEL_ID"))


def slack_log(text: str, *, always: bool = False) -> None:
    """
    Slack通知：
    - always=True の場合は SLACK_MODE に関わらず送る（致命的/重要な通知用）
    - SLACK_MODE:
        off        -> 送らない
        error_only -> 成功ログは送らない
        success    -> 成功ログも送る
    """
    if not slack_enabled():
        return
    if SLACK_MODE == "off" and not always:
        return
    if SLACK_MODE == "error_only" and (not always):
        # error_only の場合、通常ログは送らない（エラー時のみ always=True で送る）
        return

    try:
        send_slack_text(
            channel=os.environ["SLACK_CHANNEL_ID"],
            message=text,
        )
    except Exception as e:
        print(f"[WARN] Slack notify failed: {e}")


def make_basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic() -> str:
    """
    優先順位：
      1) JMA_ADV_USER / JMA_ADV_PASS から毎回生成（推奨）
      2) 予備：JMA_AUTH_BASIC をそのまま利用（Safariで観測した値）
    """
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return make_basic_auth(user.strip(), pw.strip())
    return must_env("JMA_AUTH_BASIC").strip()


def referer_for_model(model: str) -> str:
    """
    Safariで観測された Referer をモデル単位で揃える
    """
    if model == "GSM":
        return "https://www.jma.go.jp/bosai/tgv/GSM/"
    if model == "MSM":
        return "https://www.jma.go.jp/bosai/tgv/MSM/"
    if model == "LFM":
        return "https://www.jma.go.jp/bosai/tgv/LFM/"
    return "https://www.jma.go.jp/bosai/tgv/"


def headers_for(model: str) -> Dict[str, str]:
    """
    Safari互換のヘッダ（Authorization + Referer が重要）
    """
    return {
        "Authorization": get_auth_basic(),
        "User-Agent": "Mozilla/5.0",
        "Referer": referer_for_model(model),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def png_bytes_to_jpg_bytes(png_bytes: bytes, *, quality: int) -> bytes:
    """
    PNG bytes -> JPG bytes
    - subsampling=0 は 4:4:4（線画・文字が滲みにくい）
    - alphaがある場合は白背景へ
    """
    with Image.open(io.BytesIO(png_bytes)) as im:
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")

        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, subsampling=0, optimize=True)
        return buf.getvalue()


# =============================================================================
# 2) 「URLを作る」ための定義（グループ化）
# =============================================================================
#
# ここが “あなたが貼ってくれたURL群をグループ化” の実体です。
# 各グループで
#  - model: GSM/MSM/LFM
#  - init_step_hours: init探索の刻み（GSM=6h, MSM=3h, LFM=1h）
#  - ft_list: FT一覧（GSM=0..72 step3, MSM=0..27 step1, LFM=0..10 step1）
#  - maps: 実際に欲しい天気図（path + VIEWプレフィックス）
# を持ちます。
#
# NOTE:
# - init_code は UTC の "DDHHMM" を想定（例: 03日06UTC → "030600"）
# - GSMのFTは 3時間刻みで 000/003/006/... の3桁
# - MSM/LFMのFTは 200+FT の3桁（FT0=200, FT1=201,...）
# -----------------------------------------------------------------------------

def ft_list_gsm() -> List[int]:
    # GSMWide：72時間先まで（3時間刻み）
    return list(range(0, 72 + 1, 3))


def ft_list_msm() -> List[int]:
    # MSMNarrow：27時間先まで（1時間刻み）
    return list(range(0, 27 + 1, 1))


def ft_list_lfm() -> List[int]:
    # LFMNarrow：10時間先まで（1時間刻み）
    return list(range(0, 10 + 1, 1))


GROUPS: List[Dict] = [
    {
        "model": "GSM",
        "group_name": "GSM",
        "init_step_hours": 6,
        "ft_list": ft_list_gsm(),
        "maps": [
            # あなたのURL：GSMWide/300 と 3002
            # 例) FT0: VIEW3002000_RJTD_{init}.png / FT3: VIEW3002003_RJTD_{init}.png
            {"title": "GSMWide 300hPa",  "path": "GSMWide/300",  "view_prefix": "VIEW3002", "ft_mode": "gsm3"},
            {"title": "GSMWide 300hPa-2","path": "GSMWide/3002", "view_prefix": "VIEW3102", "ft_mode": "gsm3"},
        ],
    },
    {
        "model": "MSM",
        "group_name": "MSM",
        "init_step_hours": 3,
        "ft_list": ft_list_msm(),
        "maps": [
            {"title": "MSMNarrow 500hPa",  "path": "MSMNarrow/500",  "view_prefix": "VIEW500", "ft_mode": "plus200"},
            {"title": "MSMNarrow 500hPa-2","path": "MSMNarrow/5002", "view_prefix": "VIEW510", "ft_mode": "plus200"},
            {"title": "MSMNarrow 700hPa",  "path": "MSMNarrow/700",  "view_prefix": "VIEW700", "ft_mode": "plus200"},
        ],
    },
    {
        "model": "LFM",
        "group_name": "LFM",
        "init_step_hours": 1,
        "ft_list": ft_list_lfm(),
        "maps": [
            {"title": "LFMNarrow 850hPa",  "path": "LFMNarrow/850",  "view_prefix": "VIEW850", "ft_mode": "plus200"},
            {"title": "LFMNarrow 850hPa-2","path": "LFMNarrow/8502", "view_prefix": "VIEW860", "ft_mode": "plus200"},
            {"title": "LFMNarrow 925hPa",  "path": "LFMNarrow/925",  "view_prefix": "VIEW920", "ft_mode": "plus200"},
            {"title": "LFMNarrow 975hPa",  "path": "LFMNarrow/975",  "view_prefix": "VIEW970", "ft_mode": "plus200"},
            {"title": "LFMNarrow sfc",     "path": "LFMNarrow/sfc",  "view_prefix": "VIEW000", "ft_mode": "plus200"},
            {"title": "LFMNarrow sfc-2",   "path": "LFMNarrow/sfc2", "view_prefix": "VIEW010", "ft_mode": "plus200"},
        ],
    },
]


BASE = "https://www.jma.go.jp/bosai/tgv/data"


def build_url(model: str, path: str, view_prefix: str, ft_mode: str, ft: int, init_code: str) -> str:
    """
    URL生成（観測ルール）
    - gsm3: view_prefix + FT(3桁) 例: VIEW3002 + 003
    - plus200: view_prefix + (200+FT)(3桁) 例: VIEW850 + 200, VIEW850 + 201...
    """
    if ft_mode == "gsm3":
        ft_part = f"{ft:03d}"  # 000/003/006/...
        view = f"{view_prefix}{ft_part}"
    elif ft_mode == "plus200":
        view = f"{view_prefix}{200 + ft:03d}"  # 200/201/202/...
    else:
        raise ValueError(f"Unknown ft_mode: {ft_mode}")

    return f"{BASE}/{path}/images/{view}_RJTD_{init_code}.png"


# =============================================================================
# 3) HTTP取得（401/403/404の扱い）
# =============================================================================

def http_get_png(url: str, *, model: str) -> requests.Response:
    """
    - 401/403 は認証/Referer系の問題 → 即エラー扱い（リトライしても直らないことが多い）
    - 404 は「そのFTがまだ無い / initが違う / VIEWの規則違い」 → 欠損扱いで続行する設計
    """
    last_err: Optional[str] = None

    for i in range(1, HTTP_RETRY + 1):
        try:
            r = requests.get(url, headers=headers_for(model), timeout=HTTP_TIMEOUT_SEC)
            # 認証系は即終了
            if r.status_code in (401, 403):
                r.raise_for_status()
            return r
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"[WARN] HTTP try {i}/{HTTP_RETRY} failed: {last_err}")
            if i < HTTP_RETRY:
                import time
                time.sleep(HTTP_RETRY_WAIT_SEC)

    raise RuntimeError(f"HTTP failed after {HTTP_RETRY} retries: {last_err}")


def find_latest_init_for_group(group: Dict) -> str:
    """
    最新の取得できる init_code を探す。
    - groupの先頭mapの FT=0 を “プローブ” として使い、200が返る init を採用する。
    - 401/403 は即停止（認証問題）
    - 404 は「そのinitが無い」なので、過去へ遡って試す
    """
    model = group["model"]
    step_h = int(group["init_step_hours"])
    ft0 = 0
    probe_map = group["maps"][0]

    now_utc = datetime.now(timezone.utc)

    for k in range(INIT_PROBE_LIMIT):
        cand = now_utc - timedelta(hours=k * step_h)
        # init_code は DDHHMM（UTC）
        init_code = cand.strftime("%d%H00")

        probe_url = build_url(
            model=model,
            path=probe_map["path"],
            view_prefix=probe_map["view_prefix"],
            ft_mode=probe_map["ft_mode"],
            ft=ft0,
            init_code=init_code,
        )

        r = http_get_png(probe_url, model=model)

        if r.status_code == 200:
            print(f"[OK] init found for {model}: {init_code} (probe={probe_url})")
            return init_code

        if r.status_code == 404:
            print(f"[INFO] init not found (404) for {model}: {init_code}")
            continue

        # ここまで来たら想定外
        raise RuntimeError(f"Unexpected status {r.status_code} for probe: {probe_url}")

    raise RuntimeError(f"Could not find available init for {model} within {INIT_PROBE_LIMIT} probes.")


# =============================================================================
# 4) グループ単位で「全部のFT」を取得し、JPG個別添付の配列を作る
# =============================================================================

def fetch_group_as_jpg_attachments(group: Dict, init_code: str) -> Tuple[List[Attachment], List[str]]:
    """
    返り値：
      - attachments: [(filename.jpg, bytes, "image/jpeg"), ...]
      - errors: 欠損/失敗のログ文字列（Slack用）
    """
    model = group["model"]
    errors: List[str] = []
    atts: List[Attachment] = []

    ft_list: List[int] = group["ft_list"]
    maps: List[Dict] = group["maps"]

    for m in maps:
        title = m["title"]
        path = m["path"]
        view_prefix = m["view_prefix"]
        ft_mode = m["ft_mode"]

        for ft in ft_list:
            url = build_url(
                model=model,
                path=path,
                view_prefix=view_prefix,
                ft_mode=ft_mode,
                ft=ft,
                init_code=init_code,
            )

            r = http_get_png(url, model=model)

            if r.status_code == 200:
                try:
                    jpg = png_bytes_to_jpg_bytes(r.content, quality=JPEG_QUALITY)
                except Exception as e:
                    msg = f"{model} {title} FT={ft}: JPG convert failed: {e}"
                    print(f"[ERR] {msg}")
                    errors.append(msg)
                    continue

                # ファイル名規則： model_title_init_FTxx.jpg
                safe_title = title.replace(" ", "_").replace("/", "-")
                fname = f"{model}_{safe_title}_{init_code}_FT{ft:03d}.jpg"
                atts.append((fname, jpg, "image/jpeg"))

            elif r.status_code == 404:
                # 欠損は “よくある” 想定で、ログだけ残して続行
                msg = f"{model} {title} FT={ft}: 404 Not Found ({url})"
                print(f"[MISS] {msg}")
                errors.append(msg)
                continue

            else:
                # 401/403 は http_get_png 内で raise_for_status される想定
                msg = f"{model} {title} FT={ft}: unexpected status {r.status_code} ({url})"
                print(f"[ERR] {msg}")
                errors.append(msg)

    return atts, errors


# =============================================================================
# 5) メール送信（グループ別に3通）
# =============================================================================

def send_group_mail(group: Dict, init_code: str, atts: List[Attachment], errors: List[str]) -> None:
    """
    1通ぶん送信。
    - 個別JPG添付（MAIL_AS_ZIP が True なら ZIP にまとめる拡張も可能）
    - 失敗/欠損ログはSlackへ（この関数の外側でまとめて送る）
    """
    group_name = group["group_name"]
    subject_prefix = os.getenv("MAIL_SUBJECT_PREFIX") or os.getenv("EMAIL_SUBJECT_PREFIX") or "JMA"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"{subject_prefix} {group_name} tgv init={init_code} {now}"

    body_lines = [
        f"JMA 防災情報アドバイザー向け 専門天気図（tgv）[{group_name}] を自動取得しました。",
        f"init(UTC)= {init_code}",
        f"形式: JPG（個別添付） / quality={JPEG_QUALITY}",
        "・個人利用・非公開",
        "・GitHub Actions 実行",
        "",
    ]
    if errors:
        body_lines.append("----- 欠損/注意（404等） -----")
        body_lines.extend(errors[:50])  # メール本文が巨大になりすぎないよう制限
        if len(errors) > 50:
            body_lines.append(f"... and {len(errors) - 50} more.")
        body_lines.append("")

    body = "\n".join(body_lines)

    # 個別添付で送る（あなたの要望どおり）
    send_mail(
        subject=subject,
        body=body,
        attachment_blobs=atts,
        is_html=False,
        slack_mode="off",  # Slackはこのスクリプト側で統一的に送る
    )

    print(f"[OK] {group_name} mail sent: files={len(atts)} errors={len(errors)}")


# =============================================================================
# 6) main（3通送る）
# =============================================================================

def main() -> None:
    print("=== Start ADV JMA (TGV) ===")

    # Slackに「まとめ」を出したいので、グループごとに結果を保持
    summary_lines: List[str] = []
    any_error = False

    for group in GROUPS:
        model = group["model"]
        group_name = group["group_name"]

        print(f"\n--- Fetch group: {group_name} ---")

        try:
            init_code = find_latest_init_for_group(group)

            atts, errors = fetch_group_as_jpg_attachments(group, init_code)

            # 1枚も取れない場合は、メールを送っても意味がないのでエラー扱い
            if not atts:
                raise RuntimeError(f"{group_name}: no images fetched (init={init_code})")

            send_group_mail(group, init_code, atts, errors)

            # Slack用サマリ
            if errors:
                any_error = True
                summary_lines.append(f"⚠️ {group_name}: sent {len(atts)} JPG / missing={len(errors)} / init={init_code}")
            else:
                summary_lines.append(f"✅ {group_name}: sent {len(atts)} JPG / init={init_code}")

            # 欠損詳細は Slackへ（error_onlyの方針なので always=True で送る）
            if errors:
                # Slackは長文が辛いので、先頭だけ・件数・代表例
                head = "\n".join(errors[:20])
                slack_log(
                    f"⚠️ {group_name} 欠損ログ（先頭20件 / 全{len(errors)}件）\n{head}",
                    always=True,
                )

        except Exception as e:
            any_error = True
            err_msg = f"❌ {group_name} failed: {type(e).__name__}: {e}"
            print(err_msg)
            summary_lines.append(err_msg)

            # 致命エラーはSlackへ
            slack_log(err_msg, always=True)

    # 最後にまとめをSlackへ（successモードなら成功も送る）
    summary_text = "📡 ADV JMA (TGV) summary\n" + "\n".join(summary_lines)
    if any_error:
        slack_log(summary_text, always=True)
    else:
        # success のときだけ送る
        if SLACK_MODE == "success":
            slack_log(summary_text, always=True)

    print("=== Done ADV JMA (TGV) ===")


if __name__ == "__main__":
    main()
