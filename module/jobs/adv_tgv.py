# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/adv_tgv.py
#
# ADV TGV:
#   取得 → JPG化 → itemごとにGIF化 → R2 → Notion(DB) → Discord
#
# 今回の方針:
#   - 元画像は結合しない
#   - 各itemごとに時系列GIFを作る
#   - Notionには「GIF」と「元画像JPG」を両方入れる
#   - DiscordにはGIFのみ投稿する
#
# 例:
#   GSM / 300hPa:
#     FT000, FT006, FT009, ... FT072 のJPGを取得
#     → GSM_300hPa.gif を作成
#
#   Notion:
#     GSM
#       300hPa
#         GIF
#         元画像 24枚
#
#   Discord:
#     GSM / 300hPa のGIFだけ投稿
#
# 役割分担:
#   - Notion が正本
#   - R2 は30日保持の一時公開置き場
#   - Discord は軽く見るためのビュー
# =============================================================================

from __future__ import annotations

import base64
import io
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

import requests
from PIL import Image

from module.adv_tgv.models import Item, ModelCfg, load_model_groups
from module.utils.discord_utils import (
    post_discord_complete,
    post_discord_item_image_urls,
)
from module.utils.notion_utils import (
    append_bookmark,
    append_heading,
    append_images,
    append_imported_images_from_urls,
    append_toggle,
    create_db_row,
    set_page_cover,
)
from module.utils.r2_utils import make_url, put_bytes


# =============================================================================
# 型定義
# =============================================================================

# Attachment:
#   filename, bytes, mime
Attachment = Tuple[str, bytes, str]


# =============================================================================
# Env utils
# =============================================================================

def must_env(name: str) -> str:
    """必須環境変数を取得する。存在しなければ明示的に落とす。"""
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def env_int(name: str, default: int) -> int:
    """整数の環境変数を読む。値が壊れている場合はdefaultに戻す。"""
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


def env_str(name: str, default: str = "") -> str:
    """文字列の環境変数を読む。Noneだけdefaultにする。"""
    v = os.getenv(name)
    return default if v is None else v.strip()


def env_bool(name: str, default: str = "0") -> bool:
    """1 / true / yes / on を True として扱う。"""
    v = os.getenv(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


# =============================================================================
# Discord / Notion helpers
# =============================================================================

def discord_adv_webhook_url() -> str:
    """
    ADV専用DiscordチャンネルのWebhook URL。

    優先:
      DISCORD_ADV_WEBHOOK_URL

    互換:
      DISCORD_WEBHOOK_URL
    """
    return (
        os.getenv("DISCORD_ADV_WEBHOOK_URL", "").strip()
        or os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    )


def discord_adv_enabled() -> bool:
    """DISCORD_ENABLE=1 かつ Webhook URL がある時だけ投稿する。"""
    return env_bool("DISCORD_ENABLE", "0") and bool(discord_adv_webhook_url())


def notion_page_url(page_id: str) -> str:
    """Notion page_idからブラウザURLを作る。"""
    clean = (page_id or "").replace("-", "")
    return f"https://www.notion.so/{clean}" if clean else ""


# =============================================================================
# Auth
# =============================================================================

def make_basic_auth_header(user: str, password: str) -> str:
    """Basic認証ヘッダを作る。JMA_AUTH_BASIC互換用。"""
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def get_auth_basic_header() -> str:
    """
    認証情報を取得する。

    優先:
      JMA_ADV_USER / JMA_ADV_PASS

    互換:
      JMA_AUTH_BASIC
    """
    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")

    if user and pw:
        return make_basic_auth_header(user.strip(), pw.strip())

    return must_env("JMA_AUTH_BASIC").strip()


def use_auth_enabled() -> bool:
    """TGV_USE_AUTH=0 の時だけ認証を切る。通常はON。"""
    return os.getenv("TGV_USE_AUTH", "1").strip() == "1"


def get_requests_auth_tuple() -> Optional[Tuple[str, str]]:
    """
    requests の auth=(user, pass) に渡す形式を返す。

    JMA_ADV_USER / JMA_ADV_PASS がある場合:
      requestsのBasic認証機能を使う

    ない場合:
      Authorizationヘッダ方式へ回す
    """
    if not use_auth_enabled():
        return None

    user = os.getenv("JMA_ADV_USER")
    pw = os.getenv("JMA_ADV_PASS")

    if user and pw:
        return (user.strip(), pw.strip())

    return None


# =============================================================================
# HTTP
# =============================================================================

def headers_for(referer: str) -> dict:
    """JMA画像取得用ヘッダ。必要に応じてAuthorizationも入れる。"""
    h = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    # JMA_ADV_USER/PASSがない場合だけ、JMA_AUTH_BASICを使う。
    if use_auth_enabled() and (get_requests_auth_tuple() is None):
        h["Authorization"] = get_auth_basic_header()

    return h


def http_get(url: str, *, referer: str, timeout: int) -> requests.Response:
    """画像URLを取得する。"""
    auth = get_requests_auth_tuple()
    return requests.get(url, headers=headers_for(referer), auth=auth, timeout=timeout)


# =============================================================================
# Image helpers
# =============================================================================

def png_bytes_to_jpg_bytes(png_bytes: bytes, *, quality: int = 85) -> bytes:
    """
    PNG bytesをJPEG bytesへ変換する。

    PNGに透過がある場合:
      白背景へ合成してからJPEG化する。
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


def resize_for_gif(im: Image.Image, *, max_width: int) -> Image.Image:
    """
    GIF用に画像サイズを調整する。

    目的:
      - Discordで重くなりすぎるのを防ぐ
      - GIFファイルサイズを抑える

    max_width <= 0 の場合:
      リサイズしない。
    """
    rgb = im.convert("RGB")

    if max_width <= 0:
        return rgb

    if rgb.width <= max_width:
        return rgb

    ratio = max_width / float(rgb.width)
    new_height = int(rgb.height * ratio)
    return rgb.resize((max_width, new_height), Image.LANCZOS)


def make_gif_from_attachments(
    atts: Sequence[Attachment],
    *,
    duration_ms: int = 700,
    max_width: int = 900,
) -> bytes:
    """
    Attachment一覧からアニメーションGIFを作る。

    前提:
      - attsはFT順に並んでいる
      - fetch_item_images() は cfg.ft_list 順に取得するので基本OK

    注意:
      - Discord表示を考えて、デフォルトでは幅900pxへ縮小する
      - 元画像JPGは別途R2/Notionへ保存するので、GIFは軽量ビュー用
    """
    if not atts:
        raise ValueError("no attachments for gif")

    frames: List[Image.Image] = []

    for _, blob, _ in atts:
        with Image.open(io.BytesIO(blob)) as im:
            frames.append(resize_for_gif(im, max_width=max_width))

    try:
        # GIFは全フレームのサイズが揃っている方が安全。
        # 念のため、先頭フレームのサイズへ統一する。
        base_size = frames[0].size
        normalized: List[Image.Image] = []

        for frame in frames:
            if frame.size == base_size:
                normalized.append(frame.convert("P", palette=Image.ADAPTIVE))
                continue

            canvas = Image.new("RGB", base_size, (255, 255, 255))
            canvas.paste(frame.convert("RGB"), (0, 0))
            normalized.append(canvas.convert("P", palette=Image.ADAPTIVE))

        out = io.BytesIO()
        normalized[0].save(
            out,
            format="GIF",
            save_all=True,
            append_images=normalized[1:],
            duration=duration_ms,
            loop=0,
            optimize=True,
        )
        return out.getvalue()

    finally:
        for frame in frames:
            try:
                frame.close()
            except Exception:
                pass


# =============================================================================
# URL rules
# =============================================================================

def fmt_rjtd(init_dt_utc: datetime, minute: int) -> str:
    """RJTD_281200 の 281200 部分を作る。"""
    dt = init_dt_utc.astimezone(timezone.utc).replace(
        minute=minute,
        second=0,
        microsecond=0,
    )
    return dt.strftime("%d%H%M")


def floor_to_step(dt_utc: datetime, step_hours: int, minute: int) -> datetime:
    """指定step時間へ丸める。初期値探索用。"""
    dt = dt_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)
    h = (dt.hour // step_hours) * step_hours
    return dt.replace(hour=h, minute=minute)


def build_png_url(base: str, layer: str, view_code: str, rjtd: str) -> str:
    """JMA画像URLを組み立てる。"""
    return f"{base}/{layer}/images/VIEW{view_code}_RJTD_{rjtd}.png"


def view_for_ft(view_base: str, ft_hours: int, digits: int) -> str:
    """
    item.view_base の末尾FT部分だけ差し替える。

    例:
      view_base=3001000, ft=6, digits=3
      → 3001006
    """
    return f"{view_base[:-digits]}{ft_hours:0{digits}d}"


# =============================================================================
# Fetch / R2
# =============================================================================

def r2_enabled() -> bool:
    return env_bool("R2_ENABLE", "1")


def fetch_item_images(
    model_name: str,
    cfg: ModelCfg,
    init_dt: datetime,
    item: Item,
) -> Tuple[List[Attachment], bool]:
    """
    1つのitemについて、全FT画像を取得する。

    戻り値:
      - JPG Attachment一覧
      - auth_failed

    ここでは結合しない。
    GIF作成もここではしない。
    あくまで元画像JPGの取得だけを担当する。
    """
    quality = env_int("JPG_QUALITY", 85)
    timeout = env_int("HTTP_TIMEOUT", 60)

    atts: List[Attachment] = []
    auth_failed = False

    for ft in cfg.ft_list:
        view_code = view_for_ft(item.view_base, ft, item.view_digits)
        rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)
        url = build_png_url(item.base, item.layer, view_code, rjtd)

        try:
            r = http_get(url, referer=cfg.referer, timeout=timeout)

            if r.status_code in (401, 403):
                auth_failed = True
                break

            if r.status_code != 200:
                # 更新遅れや未提供FTはあり得るので、ここでは落とさず飛ばす。
                continue

            jpg = png_bytes_to_jpg_bytes(r.content, quality=quality)
            fn = f"{item.jpg_prefix}_FT{ft:03d}_VIEW{view_code}_RJTD_{rjtd}.jpg"

            atts.append((fn, jpg, "image/jpeg"))

        except Exception as e:
            print(f"[WARN] fetch failed: {model_name} {item.label} FT={ft}: {e}")
            continue

    return atts, auth_failed


def upload_attachments_to_r2(
    *,
    run_prefix: str,
    model_name: str,
    item_label: str,
    atts: Sequence[Attachment],
    subdir: str,
) -> List[str]:
    """
    AttachmentをR2へアップロードする共通関数。

    保存先:
      {run_prefix}/{model_name}/{item_label}/{subdir}/{filename}

    subdir:
      originals ... 元JPG
      gif       ... アニメGIF
    """
    if not r2_enabled():
        return []

    urls: List[str] = []

    for fn, blob, mime in atts:
        key = f"{run_prefix}/{model_name}/{item_label}/{subdir}/{fn}"
        put_bytes(key, blob, content_type=mime)
        urls.append(make_url(key))

    return urls


def find_working_init_dt(
    model_name: str,
    cfg: ModelCfg,
    max_back_hours: int,
) -> datetime:
    """
    実際に画像が存在する初期時刻を探す。

    最新の初期時刻がまだ公開されていないことがあるため、
    6時間刻みで過去へ戻りながら probe item を確認する。
    """
    timeout = env_int("HTTP_TIMEOUT", 30)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    step_hours = 6
    minute = cfg.rjtd_minute
    probe = cfg.init_probe_item

    if not cfg.ft_list:
        raise RuntimeError(f"{model_name}: cfg.ft_list is empty")

    ft0 = cfg.ft_list[0]

    for back in range(0, max_back_hours + 1, step_hours):
        init_dt = now - timedelta(hours=back)
        init_dt = floor_to_step(init_dt, step_hours=step_hours, minute=minute)

        view_code = view_for_ft(probe.view_base, ft0, probe.view_digits)
        rjtd = fmt_rjtd(init_dt, minute)
        url = build_png_url(probe.base, probe.layer, view_code, rjtd)

        r = http_get(url, referer=cfg.referer, timeout=timeout)

        if r.status_code == 200:
            return init_dt

        if r.status_code in (401, 403):
            raise RuntimeError(f"auth failed HTTP={r.status_code}")

    raise RuntimeError("INIT not found")


# =============================================================================
# Guidance links
# =============================================================================

GUIDE_ENABLE = env_bool("GUIDE_ENABLE", "1")

GUIDE_LINKS: List[Tuple[str, str]] = [
    ("ガイダンス（降水）", "https://www.jma.go.jp/bosai/advisor/guid_table.html"),
    ("ガイダンス（風）", "https://www.jma.go.jp/bosai/advisor/guid_table_wind.html"),
    ("ガイダンス（寒気）", "https://www.jma.go.jp/bosai/advisor/cold_table.html"),
]


# =============================================================================
# Notion image import
# =============================================================================

def notion_import_images_enabled() -> bool:
    """
    Notionを正本にするため、R2の外部URLをNotion管理ストレージへ取り込む。
    0の場合は従来どおり外部URL画像として埋め込む。
    """
    return env_bool("NOTION_IMPORT_IMAGES", "0")


def notion_import_timeout_seconds() -> int:
    return env_int("NOTION_IMPORT_TIMEOUT_SECONDS", 240)


def notion_import_poll_seconds() -> float:
    v = os.getenv("NOTION_IMPORT_POLL_SECONDS")
    if v is None or v.strip() == "":
        return 2.0
    try:
        return float(v.strip())
    except Exception:
        return 2.0


def append_notion_images(
    page_or_block_id: str,
    urls: List[str],
    *,
    filenames: Optional[List[str]] = None,
    content_type: str = "image/jpeg",
    chunk: int = 30,
) -> None:
    """
    Notion画像追加の共通入口。
    NOTION_IMPORT_IMAGES=1 のときはNotion側へファイルを取り込む。
    失敗した場合は従来の外部URL埋め込みへフォールバックする。
    """
    urls = [u for u in (urls or []) if u]
    if not urls:
        return

    if notion_import_images_enabled():
        items = []
        for idx, url in enumerate(urls):
            if filenames and idx < len(filenames) and filenames[idx]:
                fname = filenames[idx]
            else:
                ext = ".gif" if content_type == "image/gif" else ".jpg"
                fname = f"image_{idx + 1:03d}{ext}"
            items.append((fname, url, content_type))

        try:
            append_imported_images_from_urls(
                page_or_block_id,
                items,
                chunk=10,
                timeout_seconds=notion_import_timeout_seconds(),
                poll_seconds=notion_import_poll_seconds(),
            )
            return
        except Exception as e:
            print(f"[WARN] Notion import failed; fallback to external images: {e}")

    append_images(page_or_block_id, urls, chunk=chunk)


# =============================================================================
# Discord
# =============================================================================

def notify_discord_adv_gif(
    *,
    model_name: str,
    item_label: str,
    gif_urls: List[str],
    init_dt: datetime,
    rjtd: str,
) -> None:
    """
    ADV item単位のDiscord投稿。

    重要:
      DiscordにはGIFだけ投稿する。
      元JPGはNotion/R2に残す。
    """
    if not discord_adv_enabled() or not gif_urls:
        return

    jst = timezone(timedelta(hours=9))
    init_jst = init_dt.astimezone(jst).strftime("%Y-%m-%d %H:%M JST")

    post_discord_item_image_urls(
        webhook_url=discord_adv_webhook_url(),
        title=f"ADV TGV {model_name} / {item_label} GIF",
        image_urls=gif_urls,
        notion_url="",
        rjtd=rjtd,
        init_jst=init_jst,
    )


def notify_discord_adv_complete(
    *,
    page_id: str,
    errors: List[str],
    attach_count: int,
) -> None:
    """
    ADV完了通知。

    attach_count:
      Discordに投稿したGIF数として扱う。
    """
    if not discord_adv_enabled():
        return

    post_discord_complete(
        webhook_url=discord_adv_webhook_url(),
        category="ADV TGV",
        notion_url="",
        attach_count=attach_count,
        errors=errors,
    )


# =============================================================================
# main
# =============================================================================

def main() -> None:
    print("=== Start ADV JMA TGV GIF ===")

    errors: List[str] = []

    # total_original_images:
    #   Notion/R2へ保存した元JPGの総数。
    #
    # total_gifs:
    #   Discordへ投稿したGIFの総数。
    total_original_images = 0
    total_gifs = 0

    search_hours = env_int("INIT_SEARCH_HOURS", 72)
    r2_prefix = env_str("R2_PREFIX", "adv-tgv").strip().strip("/")

    gif_enable = env_bool("ADV_GIF_ENABLE", "1")
    gif_duration_ms = env_int("ADV_GIF_DURATION_MS", 700)
    gif_max_width = env_int("ADV_GIF_MAX_WIDTH", 900)

    print(f"[DEBUG] TGV_USE_AUTH={os.getenv('TGV_USE_AUTH','')}")
    print(f"[DEBUG] INIT_SEARCH_HOURS={search_hours}")
    print(f"[DEBUG] R2_ENABLE={os.getenv('R2_ENABLE','')}")
    print(f"[DEBUG] NOTION_ENABLE={os.getenv('NOTION_ENABLE','')}")
    print(f"[DEBUG] DISCORD_ENABLE={os.getenv('DISCORD_ENABLE','')}")
    print(f"[DEBUG] DISCORD_ADV_WEBHOOK_URL set={bool(discord_adv_webhook_url())}")
    print(f"[DEBUG] R2_PREFIX={r2_prefix}")
    print(f"[DEBUG] GUIDE_ENABLE={GUIDE_ENABLE}")
    print(f"[DEBUG] ADV_GIF_ENABLE={gif_enable}")
    print(f"[DEBUG] ADV_GIF_DURATION_MS={gif_duration_ms}")
    print(f"[DEBUG] ADV_GIF_MAX_WIDTH={gif_max_width}")
    print(f"[DEBUG] NOTION_IMPORT_IMAGES={os.getenv('NOTION_IMPORT_IMAGES','')}")
    print(f"[DEBUG] NOTION_IMPORT_TIMEOUT_SECONDS={os.getenv('NOTION_IMPORT_TIMEOUT_SECONDS','')}")
    print(f"[DEBUG] NOTION_IMPORT_POLL_SECONDS={os.getenv('NOTION_IMPORT_POLL_SECONDS','')}")

    groups = load_model_groups()

    # NotionタイトルとR2 prefixの基準はGSMの初期値に合わせる。
    init_dt_for_title = find_working_init_dt(
        "GSM",
        groups["GSM"],
        max_back_hours=search_hours,
    )

    rjtd_for_title = fmt_rjtd(
        init_dt_for_title,
        groups["GSM"].rjtd_minute,
    )

    jst = timezone(timedelta(hours=9))
    init_jst_iso = init_dt_for_title.astimezone(jst).isoformat()

    day = init_dt_for_title.strftime("%Y%m%d")
    run_prefix = f"{r2_prefix}/{day}/RJTD_{rjtd_for_title}"

    title = (
        "ADV TGV GIF / "
        f"{init_dt_for_title.astimezone(jst).strftime('%Y%m%d %H:%M')} JST"
    )

    page_id = create_db_row(
        title=title,
        category="ADV",
        init_jst_iso=init_jst_iso,
        memo="DiscordはGIFのみ。NotionにはGIFと元画像JPGを保存。R2は30日保持の一時置き場。",
        rjtd=rjtd_for_title,
        prefix=run_prefix,
        r2_url="",
        autogen=True,
    )

    print(f"[OK] Notion DB row created: {page_id}")
    print(f"[OK] Notion URL: {notion_page_url(page_id)}")

    if GUIDE_ENABLE:
        append_heading(page_id, "ガイダンス（リンク）", level=2)

        for caption, url in GUIDE_LINKS:
            append_bookmark(page_id, url, caption=caption)

    first_cover_url: Optional[str] = None

    for model_name in ("GSM", "MSM", "LFM"):
        cfg: ModelCfg = groups[model_name]

        print(f"\n--- Fetch model: {model_name} items={len(cfg.items)} ---")

        try:
            init_dt = find_working_init_dt(
                model_name,
                cfg,
                max_back_hours=search_hours,
            )

        except Exception as e:
            msg = f"{model_name}: INIT/auth failed ({type(e).__name__})"
            print(f"[NG] {msg}: {e}")
            errors.append(msg)
            continue

        rjtd = fmt_rjtd(init_dt, cfg.rjtd_minute)

        append_heading(page_id, model_name, level=2)
        model_parent: str = page_id

        for item in cfg.items:
            atts, auth_failed = fetch_item_images(
                model_name=model_name,
                cfg=cfg,
                init_dt=init_dt,
                item=item,
            )

            if auth_failed:
                msg = f"{model_name}: auth error while fetching {item.label}"
                print(f"[NG] {msg}")
                errors.append(msg)
                break

            if not atts:
                msg = f"{model_name} {item.label}: no images"
                print(f"[WARN] {msg}")
                errors.append(msg)
                continue

            # -----------------------------------------------------------------
            # 1. 元画像JPGをR2へ保存
            # -----------------------------------------------------------------
            original_urls = upload_attachments_to_r2(
                run_prefix=run_prefix,
                model_name=model_name,
                item_label=item.label,
                atts=atts,
                subdir="originals",
            )

            if not original_urls:
                msg = f"{model_name} {item.label}: original R2 urls empty"
                print(f"[WARN] {msg}")
                errors.append(msg)
                continue

            total_original_images += len(original_urls)

            if first_cover_url is None:
                first_cover_url = original_urls[0]
                # NOTION_IMPORT_IMAGES=1 ではR2を30日後に消すため、
                # R2 URLをページカバーにしない。
                if not notion_import_images_enabled():
                    set_page_cover(page_id, first_cover_url)

            # -----------------------------------------------------------------
            # 2. itemごとの時系列GIFを作成してR2へ保存
            # -----------------------------------------------------------------
            gif_urls: List[str] = []

            if gif_enable:
                try:
                    gif_blob = make_gif_from_attachments(
                        atts,
                        duration_ms=gif_duration_ms,
                        max_width=gif_max_width,
                    )

                    safe_label = item.label.replace("/", "-")
                    gif_name = f"{model_name}_{safe_label}_RJTD_{rjtd}.gif"

                    gif_urls = upload_attachments_to_r2(
                        run_prefix=run_prefix,
                        model_name=model_name,
                        item_label=item.label,
                        atts=[(gif_name, gif_blob, "image/gif")],
                        subdir="gif",
                    )

                    if gif_urls:
                        total_gifs += len(gif_urls)
                        print(f"[OK] GIF created: {model_name} {item.label}")

                    else:
                        msg = f"{model_name} {item.label}: GIF R2 urls empty"
                        print(f"[WARN] {msg}")
                        errors.append(msg)

                except Exception as e:
                    msg = f"{model_name} {item.label}: GIF create failed ({e})"
                    print(f"[WARN] {msg}")
                    errors.append(msg)

            # -----------------------------------------------------------------
            # 3. NotionにはGIFと元画像を両方入れる
            # -----------------------------------------------------------------
            item_title = (
                f"{item.label}  "
                f"(GIF {len(gif_urls)} / originals {len(original_urls)})"
            )
            item_toggle_id = append_toggle(model_parent, item_title)
            notion_parent = item_toggle_id or model_parent

            if gif_urls:
                append_heading(notion_parent, "GIF", level=3)
                gif_names = [f"{model_name}_{item.label.replace('/', '-')}_RJTD_{rjtd}.gif"]
                append_notion_images(
                    notion_parent,
                    gif_urls,
                    filenames=gif_names,
                    content_type="image/gif",
                    chunk=30,
                )

            append_heading(notion_parent, "元画像", level=3)
            original_names = [fn for fn, _blob, _mime in atts]
            append_notion_images(
                notion_parent,
                original_urls,
                filenames=original_names,
                content_type="image/jpeg",
                chunk=30,
            )

            print(
                f"[OK] R2+Notion: {model_name} {item.label} "
                f"gif={len(gif_urls)} originals={len(original_urls)}"
            )

            # -----------------------------------------------------------------
            # 4. DiscordにはGIFだけ投稿する
            # -----------------------------------------------------------------
            if gif_urls:
                try:
                    notify_discord_adv_gif(
                        model_name=model_name,
                        item_label=item.label,
                        gif_urls=gif_urls,
                        init_dt=init_dt,
                        rjtd=rjtd,
                    )

                    if discord_adv_enabled():
                        print(f"[OK] Discord GIF sent: {model_name} {item.label}")

                except Exception as e:
                    print(
                        "[WARN] Discord GIF send failed: "
                        f"{model_name} {item.label}: {e}"
                    )

    try:
        notify_discord_adv_complete(
            page_id=page_id,
            errors=errors,
            attach_count=total_gifs,
        )

        if discord_adv_enabled():
            print("[OK] Discord complete sent")

    except Exception as e:
        print(f"[WARN] Discord complete send failed: {e}")

    print(
        "\n=== Done ADV JMA TGV GIF ===\n"
        f"original_images={total_original_images}, gifs={total_gifs}"
    )


if __name__ == "__main__":
    main()
