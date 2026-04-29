# -*- coding: utf-8 -*-
# =============================================================================
# module/jobs/adv_tgv.py
#
# ADV TGV:
#   取得 → 同時刻FTごとに縦結合 → JPG化 → R2 → Notion(DB) → Discord
#
# 今回の整理:
#   - item単位で大量投稿する方式をやめる
#   - モデルごとに全itemを取得
#   - 同じ予想時刻 FT000 / FT006 / ... を縦に結合
#   - 結合済み画像だけを R2 / Notion / Discord に流す
#
# 例:
#   GSM:
#     300hPa + 300hPa-2 を FTごとに縦結合
#     48枚 → 24枚
#
#   MSM:
#     sfc / sfc-2 は除外
#     500hPa + 500hPa-2 + 700hPa + 850hPa-2 + 050 を FTごとに縦結合
#
#   LFM:
#     850hPa + 925hPa + 975hPa + sfc + sfc-2 を FTごとに縦結合
#
# 役割分担:
#   - R2 / Notion が正本
#   - Discord は画像ビューア
# =============================================================================

from __future__ import annotations

import base64
import io
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

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
    append_toggle,
    create_db_row,
    set_page_cover,
)
from module.utils.r2_utils import make_url, put_bytes


# =============================================================================
# 型定義
# =============================================================================

# 通常の添付データ:
#   filename, bytes, mime
Attachment = Tuple[str, bytes, str]

# FT付き添付データ:
#   ft_hour, Attachment
TimedAttachment = Tuple[int, Attachment]


# =============================================================================
# Env utils
# =============================================================================

def must_env(name: str) -> str:
    """必須環境変数を取得する。なければ明示的に落とす。"""
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env: {name}")
    return v


def env_int(name: str, default: int) -> int:
    """整数環境変数。壊れた値なら安全側でdefaultを返す。"""
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except Exception:
        return default


def env_str(name: str, default: str = "") -> str:
    """文字列環境変数。Noneだけdefaultにする。"""
    v = os.getenv(name)
    return default if v is None else v.strip()


def env_bool(name: str, default: str = "0") -> bool:
    """1/true/yes/on を True として扱う。"""
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
    """Notion page_id からブラウザURLを作る。"""
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

    JMA_ADV_USER / JMA_ADV_PASS がある場合は requests 側の
    Basic認証機能を使う。ない場合は Authorization ヘッダ方式へ回す。
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
    """JMA画像取得用ヘッダ。認証方式に応じてAuthorizationも入れる。"""
    h = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    # user/pass がない場合だけ、JMA_AUTH_BASIC形式を使う。
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
    """PNG bytes を白背景JPEG bytesへ変換する。"""
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


def concat_jpgs_vert(
    jpg_list: Sequence[bytes],
    *,
    quality: int = 85,
    padding: int = 12,
) -> bytes:
    """
    複数JPEGを縦方向に結合する。

    幅が違う場合:
      - 一番広い画像幅に合わせる
      - 狭い画像は中央寄せ
      - 背景は白
    """
    ims = [Image.open(io.BytesIO(b)).convert("RGB") for b in jpg_list]

    try:
        width = max(im.width for im in ims)
        height = sum(im.height for im in ims) + padding * (len(ims) - 1)

        canvas = Image.new("RGB", (width, height), (255, 255, 255))

        y = 0
        for im in ims:
            x = (width - im.width) // 2
            canvas.paste(im, (x, y))
            y += im.height + padding

        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()

    finally:
        for im in ims:
            try:
                im.close()
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
    """指定step時間へ丸める。GSM/MSM/LFMの初期値探索用。"""
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
# Fetch
# =============================================================================

def fetch_item_images_with_ft(
    model_name: str,
    cfg: ModelCfg,
    init_dt: datetime,
    item: Item,
) -> Tuple[List[TimedAttachment], bool]:
    """
    1つのitemについて、全FT画像を取得する。

    戻り値:
      - [(ft, attachment), ...]
      - auth_failed
    """
    quality = env_int("JPG_QUALITY", 85)
    timeout = env_int("HTTP_TIMEOUT", 60)

    atts: List[TimedAttachment] = []
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
                # ないFTは静かに飛ばす。JMA側の更新遅れ対策。
                continue

            jpg = png_bytes_to_jpg_bytes(r.content, quality=quality)
            fn = f"{item.jpg_prefix}_FT{ft:03d}_VIEW{view_code}_RJTD_{rjtd}.jpg"

            atts.append((ft, (fn, jpg, "image/jpeg")))

        except Exception as e:
            print(f"[WARN] fetch failed: {model_name} {item.label} FT={ft}: {e}")
            continue

    return atts, auth_failed


def find_working_init_dt(
    model_name: str,
    cfg: ModelCfg,
    max_back_hours: int,
) -> datetime:
    """
    実際に画像が存在する初期時刻を探す。

    最新時刻がまだ公開されていないことがあるため、
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
# Vertical join rules
# =============================================================================

def target_items_for_model(model_name: str, items: Sequence[Item]) -> List[Item]:
    """
    モデルごとの結合対象itemを決める。

    MSM:
      sfc / sfc-2 は廃止するため除外。

    GSM / LFM:
      現在の models.py 定義にあるitemをそのまま使う。
    """
    if model_name == "MSM":
        return [item for item in items if item.label not in ("sfc", "sfc-2")]

    return list(items)


def build_vertical_ft_attachments(
    *,
    model_name: str,
    cfg: ModelCfg,
    init_dt: datetime,
    items: Sequence[Item],
) -> Tuple[List[Attachment], List[str], bool]:
    """
    モデル内の複数itemを取得し、同じFTごとに縦結合する。

    例:
      LFM FT004:
        850hPa
        925hPa
        975hPa
        sfc
        sfc-2
      を1枚の縦長JPEGへする。
    """
    quality = env_int("JPG_QUALITY", 85)
    padding = env_int("ADV_VERTICAL_PADDING", 12)

    by_ft: Dict[int, List[Tuple[str, Attachment]]] = {}
    errors: List[str] = []

    for item in items:
        timed_atts, auth_failed = fetch_item_images_with_ft(
            model_name=model_name,
            cfg=cfg,
            init_dt=init_dt,
            item=item,
        )

        if auth_failed:
            return [], errors, True

        if not timed_atts:
            msg = f"{model_name} {item.label}: no images"
            print(f"[WARN] {msg}")
            errors.append(msg)
            continue

        for ft, att in timed_atts:
            by_ft.setdefault(ft, []).append((item.label, att))

    merged: List[Attachment] = []

    for ft in cfg.ft_list:
        group = by_ft.get(ft, [])
        if not group:
            continue

        # 取得順は target_items_for_model() の順を保つ。
        blobs = [att[1] for _, att in group]

        try:
            jpg = concat_jpgs_vert(blobs, quality=quality, padding=padding)
        except Exception as e:
            msg = f"{model_name} FT{ft:03d}: vertical join failed ({e})"
            print(f"[WARN] {msg}")
            errors.append(msg)
            continue

        labels = "_".join(label.replace("/", "-") for label, _ in group)
        fn = f"{model_name}_FT{ft:03d}_vertical_{labels}.jpg"

        merged.append((fn, jpg, "image/jpeg"))

    return merged, errors, False


# =============================================================================
# R2
# =============================================================================

def r2_enabled() -> bool:
    return env_bool("R2_ENABLE", "1")


def upload_model_vertical_images_to_r2(
    *,
    run_prefix: str,
    model_name: str,
    atts: Sequence[Attachment],
) -> List[str]:
    """
    縦結合済み画像をR2へアップロードする。

    保存先:
      {run_prefix}/{model_name}/vertical/{filename}
    """
    if not r2_enabled():
        return []

    urls: List[str] = []

    for fn, blob, mime in atts:
        key = f"{run_prefix}/{model_name}/vertical/{fn}"
        put_bytes(key, blob, content_type=mime)
        urls.append(make_url(key))

    return urls


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
# Discord
# =============================================================================

def notify_discord_adv_model(
    *,
    model_name: str,
    urls: List[str],
    init_dt: datetime,
    rjtd: str,
) -> None:
    """モデル単位でDiscordへ画像投稿する。"""
    if not discord_adv_enabled() or not urls:
        return

    jst = timezone(timedelta(hours=9))
    init_jst = init_dt.astimezone(jst).strftime("%Y-%m-%d %H:%M JST")

    post_discord_item_image_urls(
        webhook_url=discord_adv_webhook_url(),
        title=f"ADV TGV {model_name} / vertical FT",
        image_urls=urls,
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
    """完了通知。最後にNotion URLを出す。"""
    if not discord_adv_enabled():
        return

    post_discord_complete(
        webhook_url=discord_adv_webhook_url(),
        category="ADV TGV",
        notion_url=notion_page_url(page_id),
        attach_count=attach_count,
        errors=errors,
    )


# =============================================================================
# main
# =============================================================================

def main() -> None:
    print("=== Start ADV JMA TGV vertical ===")

    errors: List[str] = []
    total_images = 0

    search_hours = env_int("INIT_SEARCH_HOURS", 72)
    r2_prefix = env_str("R2_PREFIX", "adv-tgv").strip().strip("/")

    print(f"[DEBUG] TGV_USE_AUTH={os.getenv('TGV_USE_AUTH','')}")
    print(f"[DEBUG] INIT_SEARCH_HOURS={search_hours}")
    print(f"[DEBUG] R2_ENABLE={os.getenv('R2_ENABLE','')}")
    print(f"[DEBUG] NOTION_ENABLE={os.getenv('NOTION_ENABLE','')}")
    print(f"[DEBUG] DISCORD_ENABLE={os.getenv('DISCORD_ENABLE','')}")
    print(f"[DEBUG] DISCORD_ADV_WEBHOOK_URL set={bool(discord_adv_webhook_url())}")
    print(f"[DEBUG] R2_PREFIX={r2_prefix}")
    print(f"[DEBUG] GUIDE_ENABLE={GUIDE_ENABLE}")
    print(f"[DEBUG] ADV_VERTICAL_PADDING={env_int('ADV_VERTICAL_PADDING', 12)}")

    groups = load_model_groups()

    # タイトルやrun_prefixの基準はGSMの初期時刻に合わせる。
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
        "ADV TGV vertical / "
        f"{init_dt_for_title.astimezone(jst).strftime('%Y%m%d %H:%M')} JST"
    )

    page_id = create_db_row(
        title=title,
        category="ADV",
        init_jst_iso=init_jst_iso,
        memo="同時刻FTごとに縦結合",
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

        print(f"\n--- Fetch model vertical: {model_name} items={len(cfg.items)} ---")

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
        items = target_items_for_model(model_name, cfg.items)

        print(
            "[INFO] vertical items: "
            + ", ".join(item.label for item in items)
        )

        atts, model_errors, auth_failed = build_vertical_ft_attachments(
            model_name=model_name,
            cfg=cfg,
            init_dt=init_dt,
            items=items,
        )

        errors.extend(model_errors)

        if auth_failed:
            msg = f"{model_name}: auth error while fetching images"
            print(f"[NG] {msg}")
            errors.append(msg)
            continue

        if not atts:
            msg = f"{model_name}: no vertical images"
            print(f"[WARN] {msg}")
            errors.append(msg)
            continue

        urls = upload_model_vertical_images_to_r2(
            run_prefix=run_prefix,
            model_name=model_name,
            atts=atts,
        )

        if not urls:
            msg = f"{model_name}: R2 urls empty"
            print(f"[WARN] {msg}")
            errors.append(msg)
            continue

        total_images += len(urls)

        if first_cover_url is None:
            first_cover_url = urls[0]
            set_page_cover(page_id, first_cover_url)

        append_heading(page_id, model_name, level=2)

        item_title = f"{model_name} vertical FT  ({len(urls)} images)"
        toggle_id = append_toggle(page_id, item_title)

        if toggle_id:
            append_images(toggle_id, urls, chunk=30)
        else:
            append_images(page_id, urls, chunk=30)

        print(f"[OK] R2+Notion vertical: {model_name} urls={len(urls)}")

        try:
            notify_discord_adv_model(
                model_name=model_name,
                urls=urls,
                init_dt=init_dt,
                rjtd=rjtd,
            )

            if discord_adv_enabled():
                print(f"[OK] Discord model sent: {model_name}")

        except Exception as e:
            print(f"[WARN] Discord model send failed: {model_name}: {e}")

    try:
        notify_discord_adv_complete(
            page_id=page_id,
            errors=errors,
            attach_count=total_images,
        )

        if discord_adv_enabled():
            print("[OK] Discord complete sent")

    except Exception as e:
        print(f"[WARN] Discord complete send failed: {e}")

    print("\n=== Done ADV JMA TGV vertical ===")


if __name__ == "__main__":
    main()
