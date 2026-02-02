# -*- coding: utf-8 -*-
# =============================================================================
# scripts/jma_adv.py
#
# JMA 防災情報アドバイザー向け「専門天気図（tgv）」を自動取得し、
# “天気図ごと（itemごと）” にメール送信（必須）＋Slack投稿（任意）する。
#
# ✅ 仕様（あなたの現行URL規則に準拠）
# - FT は VIEWコード末尾で表現（RJTDは init 固定）
# - GSM: FT=3..30 (3h) 10枚 / item
# - MSM: FT=1..15(1h) + 18,21,24,27,30 合計20枚 / item
# - LFM: FT=4..18(1h) 15枚 / item（必要に応じて変更OK）
#
# ✅ 認証（ADV限定＝認証必須）
# - TGV_USE_AUTH=1 を推奨（GitHub Actions では secrets の user/pass を使う）
# - requests の auth=(user,pw) を優先（curl -u 相当で安定しやすい）
# - user/pass が無い環境は Authorization ヘッダ（JMA_AUTH_BASIC）にフォールバック
#
# ✅ Slack
# - DELIVERY_MODE=slack / both のときに画像を投稿
# - それ以外でも「エラー通知」は Slack トークン/チャンネルがあれば送る
#
# ✅ 画像結合（今回の要望：3枚横結合が基本）
# - JOIN_TRIPLE=1 のとき有効（デフォルトON）
# - 3枚を横結合して 1枚にする（添付/投稿数を約1/3へ）
# - 余り2枚 → 白1枚を足して3枚幅
# - 余り1枚 → 白2枚を足して3枚幅
# - すべて同サイズで揃う想定（念のため「高さ違い」は白背景で吸収）
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
from typing import Dict, List, Tuple, Optional, Sequence

import requests
from PIL import Image

from module.utils.mail_utils import send_mail
from module.utils.slack_utils import send_slack_text, upload_bytes_slack


# -----------------------------------------------------------------------------
# 添付の型： (ファイル名, バイナリ, MIME)
# -----------------------------------------------------------------------------
Attachment = Tuple[str, bytes, str]


# =============================================================================
# Env utils
# =============================================================================
def must_env(name: str) -> str:
    """必須環境変数。無ければ即エラーで落とす。"""
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def env_int(name: str, default: int) -> int:
    """int環境変数。無ければ default。壊れていても default。"""
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


def env_str(name: str, default: str = "") -> str:
    """str環境変数。無ければ default。"""
    v = os.getenv(name)
    return default if v is None else v.strip()


def env_bool(name: str, default: str = "0") -> bool:
    """
    bool環境変数。
    - "1" / "true" / "yes" / "on" を True とみなす
    """
    v = os.getenv(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


# =============================================================================
# Auth
# =============================================================================
def make_basic_auth_header(user: str, password: str) -> str:
    """
    Authorization: Basic xxxx を作る（header方式）
    ※ ただしADVでは「requests auth=(user,pw)」の方が curl -u に近くて安定することが多い
    """
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic_header() -> str:
    """
    優先：user/pass → 生成、無ければ JMA_AUTH_BASIC
    ※ ここは “保険” として残す（実運用は user/pass 推奨）
    """
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return make_basic_auth_header(user.strip(), pw.strip())
    return must_env("JMA_AUTH_BASIC").strip()


def use_auth_enabled() -> bool:
    """
    ADVは認証必須なのでデフォルト 1 推奨。
    公開画像を取る用途が混ざる場合のみ 0 にする。
    """
    return os.getenv("TGV_USE_AUTH", "1").strip() == "1"


def get_requests_auth_tuple() -> Optional[Tuple[str, str]]:
    """
    curl -u と同じ挙動にするため requests の auth を使う。
    user/pass があるなら (user,pw) を返す。
    """
    if not use_auth_enabled():
        return None

    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")
    if user and pw:
        return (user.strip(), pw.strip())

    # user/pass がない場合は None（headers側で Authorization を付ける可能性）
    return None


# =============================================================================
# Slack（画像投稿 + エラー通知）
# =============================================================================
def slack_enabled() -> bool:
    return bool(env_str("SLACK_BOT_TOKEN")) and bool(env_str("SLACK_CHANNEL_ID"))


def slack_notify(text: str) -> None:
    """
    エラー通知用のテキスト投稿。
    Slackは長文で落ちることがあるので分割して送る。
    """
    if not slack_enabled():
        return

    ch = env_str("SLACK_CHANNEL_ID")
    try:
        limit = 3500
        for i in range(0, len(text), limit):
            send_slack_text(channel=ch, message=text[i:i + limit])
    except Exception as e:
        print(f"[WARN] Slack notify failed: {e}")


# =============================================================================
# HTTP
# =============================================================================
def headers_for(referer: str) -> dict:
    """
    Referer を付けないと弾かれる系のサイト対策も含む。
    ADVは認証必須だが、基本は requests の auth=(user,pw) を優先。
    """
    h = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    # user/passが無い環境向けに、ヘッダ方式も残す（JMA_AUTH_BASIC想定）
    if use_auth_enabled() and (get_requests_auth_tuple() is None):
        h["Authorization"] = get_auth_basic_header()

    return h


def http_get(url: str, *, referer: str, timeout: int) -> requests.Response:
    """
    認証：
    - requests の auth=(user,pw) があるならそれを使う（curl -u相当）
    - それが無ければ headers の Authorization に期待する
    """
    auth = get_requests_auth_tuple()
    return requests.get(
        url,
        headers=headers_for(referer),
        auth=auth,
        timeout=timeout,
    )


# =============================================================================
# 画像：変換・結合
# =============================================================================
def png_bytes_to_jpg_bytes(png_bytes: bytes, *, quality: int = 85) -> bytes:
    """
    PNGをJPEG化（メール添付/Slack投稿のサイズを少し下げられる）
    - 透過は白背景にする
    """
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


def make_white_jpg(width: int, height: int, *, quality: int = 85) -> bytes:
    """
    指定サイズの白いJPEGを生成して bytes で返す。
    余り（1枚/2枚）を「3枚幅」に揃えるために使う。
    """
    im = Image.new("RGB", (width, height), (255, 255, 255))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def concat_jpgs_horiz(jpg_list: Sequence[bytes], *, quality: int = 85) -> bytes:
    """
    JPEGを任意枚数、横方向に結合して1枚にする。
    - 高さが違う場合は白背景で最大高さに合わせて貼る（上詰め）
    """
    ims = [Image.open(io.BytesIO(b)).convert("RGB") for b in jpg_list]
    try:
        h = max(im.height for im in ims)
        w = sum(im.width for im in ims)

        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        x = 0
        for im in ims:
            canvas.paste(im, (x, 0))
            x += im.width

        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()
    finally:
        for im in ims:
            try:
                im.close()
            except Exception:
                pass


def maybe_triple_join_attachments(atts: List[Attachment], *, quality: int) -> List[Attachment]:
    """
    3枚ずつ横結合して添付数/投稿数を減らす（JOIN_TRIPLE=1 のときだけ有効）
    - 余り2枚 → 白1枚を足して3枚幅
    - 余り1枚 → 白2枚を足して3枚幅
    """
    if not env_bool("JOIN_TRIPLE", "1"):
        return atts

    if not atts:
        return atts

    joined: List[Attachment] = []

    # 基準サイズ（白画像のサイズを合わせる）
    # だいたい同じ図のはずなので、先頭のサイズに合わせる
    base_w = base_h = None
    try:
        with Image.open(io.BytesIO(atts[0][1])) as im0:
            base_w, base_h = im0.size
    except Exception:
        # 万一読めない場合は「結合を諦めてそのまま返す」
        return atts

    i = 0
    while i < len(atts):
        group = atts[i:i + 3]

        # 3枚そろうならそのまま
        if len(group) == 3:
            (fn1, b1, _m1), (_fn2, b2, _m2), (_fn3, b3, _m3) = group
            merged = concat_jpgs_horiz([b1, b2, b3], quality=quality)

            # ファイル名：先頭のftに寄せて “_3up” を付ける（追跡しやすい）
            out_name = fn1.replace(".jpg", "") + "_3up.jpg"
            joined.append((out_name, merged, "image/jpeg"))
            i += 3
            continue

        # 余り2枚 → 白1枚を追加して3枚幅
        if len(group) == 2:
            (fn1, b1, _m1), (_fn2, b2, _m2) = group
            white = make_white_jpg(base_w, base_h, quality=quality)
            merged = concat_jpgs_horiz([b1, b2, white], quality=quality)

            out_name = fn1.replace(".jpg", "") + "_3up_pad.jpg"
            joined.append((out_name, merged, "image/jpeg"))
            i += 2
            continue

        # 余り1枚 → 白2枚を追加して3枚幅
        if len(group) == 1:
            (fn1, b1, _m1) = group[0]
            white1 = make_white_jpg(base_w, base_h, quality=quality)
            white2 = make_white_jpg(base_w, base_h, quality=quality)
            merged = concat_jpgs_horiz([b1, white1, white2], quality=quality)

            out_name = fn1.replace(".jpg", "") + "_3up_pad.jpg"
            joined.append((out_name, merged, "image/jpeg"))
            i += 1
            continue

    return joined


# =============================================================================
# URL rules
# =============================================================================
def fmt_rjtd(init_dt_utc: datetime, minute: int) -> str:
    """
    RJTD の表現（あなたの現状の運用に合わせる）
    - ここでは DDHHMM を使っている（例: 060600）
    - minute は cfg.rjtd_minute を使う（現状 0）
    """
    dt = init_dt_utc.astimezone(timezone.utc).replace(minute=minute, second=0, microsecond=0)
    return dt.strftime("%d%H%M")


def floor_to_step(dt_utc: datetime, step_hours: int, minute: int) -> datetime:
    """
    INIT探索のスタート地点を「モデルの更新周期」へ寄せる。
    - step_hours=6 なら 0/6/12/18時系
    - step_hours=3 なら 0/3/6/9/...
    """
    dt = dt_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)
    h = (dt.hour // step_hours) * step_hours
    return dt.replace(hour=h, minute=minute)


def build_png_url(base: str, layer: str, view_code: str, rjtd: str) -> str:
    """最終的なPNG URL組み立て"""
    return f"{base}/{layer}/images/VIEW{view_code}_RJTD_{rjtd}.png"


def view_for_ft(view_base: str, ft_hours: int, digits: int) -> str:
    """
    FT は VIEWコード末尾で表現
    - GSM: 末尾3桁 FT（例: 3001000 -> 3001003）
    - MSM/LFM: 末尾2桁 FT（例: 500000 -> 500001）
    """
    return f"{view_base[:-digits]}{ft_hours:0{digits}d}"


# =============================================================================
# Model configs
# =============================================================================
@dataclass
class Item:
    """
    1つの天気図レイヤ（300, 500, 050...）の定義
    base は item ごとに持たせる（MSMNarrow が混ざるため超重要）
    """
    label: str
    base: str
    layer: str
    view_base: str
    view_digits: int
    jpg_prefix: str


@dataclass
class ModelCfg:
    """
    モデル単位の設定
    - rjtd_minute: RJTDの minute 固定（今は 0）
    - init_step_hours: init 探索刻み
    """
    referer: str
    init_step_hours: int
    rjtd_minute: int
    init_probe_item: Item
    ft_list: List[int]
    slack_chunk: int
    items: List[Item]


def ft_list_gsm() -> List[int]:
    # GSM: 3..30（3h）
    return list(range(3, 31, 3))


def ft_list_msm() -> List[int]:
    # MSM: 1..15(1h) + 18..30(3h)
    return list(range(1, 16)) + [18, 21, 24, 27, 30]


def ft_list_lfm() -> List[int]:
    # LFM: 今は「4から欲しい」運用（4..18）
    return list(range(4, 19))


def load_model_groups() -> Dict[str, ModelCfg]:
    slack_chunk = env_int("SLACK_CHUNK", 10)

    GSM_WIDE = "https://www.jma.go.jp/bosai/tgv/data/GSMWide"
    MSM_WIDE = "https://www.jma.go.jp/bosai/tgv/data/MSMWide"
    MSM_NAR  = "https://www.jma.go.jp/bosai/tgv/data/MSMNarrow"
    LFM_NAR  = "https://www.jma.go.jp/bosai/tgv/data/LFMNarrow"

    # --- GSM ---
    gsm_items = [
        Item("300hPa",   GSM_WIDE, "300",  "3001000", 3, "GSM_300"),
        Item("300hPa-2", GSM_WIDE, "3002", "3101000", 3, "GSM_3002"),
    ]

    # --- MSM ---
    msm_items = [
        Item("500hPa",   MSM_WIDE, "500",  "500000", 2, "MSM_500"),
        Item("500hPa-2", MSM_WIDE, "5002", "510000", 2, "MSM_5002"),
        Item("700hPa",   MSM_WIDE, "700",  "700000", 2, "MSM_700"),
        # 8502 は Narrow 側に寄せたい運用
        Item("8502",     MSM_NAR,  "8502", "860000", 2, "MSM_8502"),
        Item("050",      MSM_NAR,  "050",  "050200", 2, "MSM_050"),
    ]

    # --- LFM ---
    lfm_items = [
        Item("850hPa",   LFM_NAR, "850",  "850200", 2, "LFM_850"),
        Item("925hPa",   LFM_NAR, "925",  "920200", 2, "LFM_925"),
        Item("975hPa",   LFM_NAR, "975",  "970200", 2, "LFM_975"),
        Item("sfc",      LFM_NAR, "sfc",  "000200", 2, "LFM_sfc"),
        Item("sfc-2",    LFM_NAR, "sfc2", "010200", 2, "LFM_sfc2"),
    ]

    return {
        "GSM": ModelCfg(
            referer="https://www.jma.go.jp/bosai/tgv/GSM/",
            init_step_hours=6,
            rjtd_minute=0,   # 現状の運用：00分（RJTD=DDHH00）
            init_probe_item=gsm_items[0],
            ft_list=ft_list_gsm(),
            slack_chunk=slack_chunk,
            items=gsm_items,
        ),
        "MSM": ModelCfg(
            referer="https://www.jma.go.jp/bosai/tgv/MSM/",
            init_step_hours=3,
            rjtd_minute=0,   # 現状の運用：00分
            init_probe_item=msm_items[0],  # 500hPa をプローブにする
            ft_list=ft_list_msm(),
            slack_chunk=slack_chunk,
            items=msm_items,
        ),
        "LFM": ModelCfg(
            referer="https://www.jma.go.jp/bosai/tgv/LFM/",
            init_step_hours=6,
            rjtd_minute=0,   # 現状の運用：00分
            init_probe_item=lfm_items[0],
            ft_list=ft_list_lfm(),
            slack_chunk=slack_chunk,
            items=lfm_items,
        ),
    }


# =============================================================================
# INIT auto-detect
# =============================================================================
def probe_init(url: str, referer: str) -> Tuple[int, str, bytes]:
    """
    まず「このURLが存在するか？」を見るための軽量プローブ
    """
    r = http_get(url, referer=referer, timeout=25)
    ctype = (r.headers.get("Content-Type") or "").lower()
    head = r.content[:200]
    return r.status_code, ctype, head


def find_working_init_dt(model_name: str, cfg: ModelCfg, *, max_back_hours: int = 72) -> datetime:
    """
    INIT（RJTD）を自動探索する。
    - 認証エラー（401/403）は即座に致命扱い
    - 404は「無いだけ」なので探索継続
    """
    step = cfg.init_step_hours
    now = datetime.now(timezone.utc)
    start = floor_to_step(now, step, cfg.rjtd_minute)

    it0 = cfg.init_probe_item
    first_ft = cfg.ft_list[0]  # GSMなら3, MSMなら1, LFMなら4
    view0 = view_for_ft(it0.view_base, first_ft, it0.view_digits)

    for back in range(0, max_back_hours + 1, step):
        init_dt = start - timedelta(hours=back)
        rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)
        url = build_png_url(it0.base, it0.layer, view0, rjtd)

        st, ctype, head = probe_init(url, cfg.referer)

        if st in (401, 403):
            raise RuntimeError(f"{model_name} auth error HTTP{st} url={url}")

        if st == 200:
            # 200でHTMLが返ってくるのはログイン画面等の可能性 → 認証事故扱い
            if ("text/html" in ctype) or head.lower().startswith(b"<!doctype html") or head.lower().startswith(b"<html"):
                raise RuntimeError(f"{model_name} got HTML with HTTP200 (auth?) url={url}")
            print(f"[OK] {model_name} init found: {init_dt.isoformat()} RJTD_{rjtd} url={url}")
            return init_dt

    raise RuntimeError(f"{model_name}: init not found within back={max_back_hours}h")


# =============================================================================
# Fetch per item
# =============================================================================
def fetch_png(url: str, referer: str) -> Tuple[int, bytes, str]:
    """
    PNGを取得する。
    - status / content / content-type を返す
    """
    r = http_get(url, referer=referer, timeout=40)
    ctype = (r.headers.get("Content-Type") or "").lower()
    return r.status_code, r.content, ctype


def fetch_item_images(model_name: str, cfg: ModelCfg, init_dt: datetime, item: Item) -> Tuple[List[Attachment], bool]:
    """
    1天気図（item）ぶん取得する。
    - 404 はよくあるので黙ってスキップ
    - 401/403 or 200なのにHTML（認証ページ疑い）なら auth_failed=True
    - 最後に JOIN_TRIPLE=1 なら 3枚横結合＋白パディング
    """
    jpg_quality = env_int("JPG_QUALITY", 85)
    rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)

    raw_atts: List[Attachment] = []
    auth_failed = False

    for ft in cfg.ft_list:
        view_code = view_for_ft(item.view_base, ft, item.view_digits)

        # ★重要：base は item ごと（MSMNarrow が混ざるため）
        url = build_png_url(item.base, item.layer, view_code, rjtd)

        status, content, ctype = fetch_png(url, cfg.referer)

        if status == 200:
            # 200でHTMLは異常（ログインHTML等）
            if ("text/html" in ctype) or content[:20].lower().startswith(b"<!doctype html") or content[:10].lower().startswith(b"<html"):
                auth_failed = True
                print(f"[NG] {model_name} {item.label} ft={ft}: got HTML with HTTP200 (auth?) url={url}")
                break

            jpg = png_bytes_to_jpg_bytes(content, quality=jpg_quality)
            fname = f"{item.jpg_prefix}_ft{ft:03d}.jpg"
            raw_atts.append((fname, jpg, "image/jpeg"))
            print(f"[OK] {model_name} {item.label} ft={ft} url={url}")
            continue

        if status in (401, 403):
            auth_failed = True
            print(f"[NG] {model_name} {item.label} ft={ft}: HTTP{status} auth url={url}")
            break

        if status == 404:
            continue

        # その他のHTTPは「たまにある」ので必要ならログ復活
        # print(f"[WARN] {model_name} {item.label} ft={ft}: HTTP{status} url={url}")

    # ---- ここで「3枚横結合＋白パディング」を適用（任意） ----
    atts = maybe_triple_join_attachments(raw_atts, quality=jpg_quality)

    return atts, auth_failed


# =============================================================================
# Delivery（メール + Slack画像投稿）
# =============================================================================
def send_item_mail(model_name: str, item: Item, cfg: ModelCfg, init_dt: datetime, atts: List[Attachment]) -> None:
    """
    item単位でメール送信（添付あり）
    """
    prefix = env_str("MAIL_SUBJECT_PREFIX", "JMA")
    rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)
    subject = f"{prefix} ADV TGV {model_name} {item.label} RJTD={rjtd}"

    body = "\n".join([
        "JMA 防災情報アドバイザー向け 専門天気図（tgv）",
        f"model: {model_name}",
        f"chart: {item.label}",
        f"RJTD : {rjtd} (UTC)",
        f"files: {len(atts)}",
        "",
        "※ 個人利用・非公開",
        "※ GitHub Actions 実行",
    ])

    send_mail(
        subject=subject,
        body=body,
        attachment_blobs=atts,
        is_html=False,
        slack_mode="off",   # mail_utils 側の Slack 連携は使わない
    )
    print(f"[OK] mail sent: {model_name} {item.label} files={len(atts)}")


def send_item_slack(model_name: str, item: Item, cfg: ModelCfg, init_dt: datetime, atts: List[Attachment], chunk_size: int) -> None:
    """
    item単位で Slack に画像を投稿する（外部アップロード3-step方式：slack_utils.py）
    - chunk_size で “1投稿あたり何枚” を調整可能
    - 3枚結合していれば枚数自体が減るので、chunk_size=10 でも余裕が出る
    """
    if not slack_enabled():
        # Slackが未設定なら何もしない
        return

    channel = env_str("SLACK_CHANNEL_ID")
    if not channel:
        raise RuntimeError("SLACK_CHANNEL_ID is missing")

    rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)
    header = f"🗺️ ADV TGV {model_name} / {item.label}  RJTD={rjtd}  files={len(atts)}"

    pairs = [(fn, blob) for (fn, blob, _mime) in atts]
    for i in range(0, len(pairs), chunk_size):
        chunk = pairs[i:i + chunk_size]
        comment = header if i == 0 else f"🗺️ ADV TGV {model_name} / {item.label}（続き {i//chunk_size + 1}）"
        upload_bytes_slack(channel=channel, files=chunk, initial_comment=comment)

    posts = (len(pairs) + chunk_size - 1) // chunk_size
    print(f"[OK] slack sent: {model_name} {item.label} posts={posts}")


# =============================================================================
# main
# =============================================================================
def main() -> None:
    print("=== Start ADV JMA TGV ===")
    print(f"[DEBUG] TGV_USE_AUTH={os.getenv('TGV_USE_AUTH','')}")
    print(f"[DEBUG] JOIN_TRIPLE={os.getenv('JOIN_TRIPLE','')}")
    print(f"[DEBUG] DELIVERY_MODE={mode} slack_enabled={slack_enabled()} channel={env_str('SLACK_CHANNEL_ID','')[:6]}...")
    mode = env_str("DELIVERY_MODE", "email").lower()
    search_hours = env_int("INIT_SEARCH_HOURS", 72)

    groups = load_model_groups()

    # ※ ここは固定順。必要ならリストを変えてOK
    for model_name in ("GSM", "MSM", "LFM"):
        cfg = groups[model_name]
        print(f"\n--- Fetch model: {model_name} items={len(cfg.items)} ---")

        # 1) init探索
        try:
            init_dt = find_working_init_dt(model_name, cfg, max_back_hours=search_hours)
        except Exception as e:
            msg = f"❌ ADV TGV {model_name}: INIT not found / auth error\n{type(e).__name__}: {e}"
            print(msg)
            slack_notify(msg)
            continue

        model_total = 0
        model_auth_failed = False

        # 2) itemごとに取得 → 配信
        for item in cfg.items:
            atts, auth_failed = fetch_item_images(model_name, cfg, init_dt, item)

            if auth_failed:
                model_auth_failed = True
                slack_notify(f"❌ ADV TGV {model_name} {item.label}: auth error (401/403 or HTTP200-HTML)")
                break

            if not atts:
                print(f"[WARN] {model_name} {item.label}: no images")
                continue

            model_total += len(atts)

            # --- メール ---
            if mode in ("email", "both"):
                try:
                    send_item_mail(model_name, item, cfg, init_dt, atts)
                except Exception as e:
                    slack_notify(f"❌ ADV TGV {model_name} {item.label}: MAIL FAILED\n{type(e).__name__}: {e}")

            # --- Slack 画像投稿 ---
            if mode in ("slack", "both"):
                try:
                    send_item_slack(model_name, item, cfg, init_dt, atts, chunk_size=cfg.slack_chunk)
                except Exception as e:
                    slack_notify(f"❌ ADV TGV {model_name} {item.label}: SLACK FAILED\n{type(e).__name__}: {e}")
                    print(msg)
                    slack_notify(msg)

        # 3) モデル全滅だけ通知
        if (not model_auth_failed) and (model_total == 0):
            slack_notify(
                f"❌ ADV TGV {model_name}: no images fetched (model total=0)\nRJTD={fmt_rjtd(init_dt, cfg.rjtd_minute)}"
            )

    print("\n=== Done ADV JMA TGV ===")


if __name__ == "__main__":
    main()
