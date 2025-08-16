# -*- coding: utf-8 -*-
# =============================================================================
# module/panel_utils.py
# -----------------------------------------------------------------------------
# パネル可視化ユーティリティ（NO DATA生成・cfgrib安全open・複数列パネル生成）
#
# できること
#  - make_nodata_weather_panel(): データ欠損時の「NO DATA」画像を1枚で出力
#  - open_isobaric_dataset(): 等圧面データを安全に取得（hPa選択にも対応）
#  - open_surface_dataset(): 地上/10m層を安全に取得（instant/heightAboveGround優先）
#  - make_universal_weather_panel(): nrows × ncols の“複数列パネル”を
#      直接 1 枚で保存（列 = 連続 step、行 = 変数群）。ページ分割にも応用可。
#  - concat_panel_images_horizontally(): 既存の縦長画像をあとで横に合成
#
# 使い方のポイント
#  - panel_def は [(plot_func, dataset_or_dict, title), ...] のリスト（行＝変数）
#  - ncols を 2,3,4… とすると +0h, +3h, +6h ... のように「列方向に時間を並べた1枚」を生成
#  - step=None の場合は「列 0..(ncols-1) の step を自動で採用」
#    start_step を与えると（例: start_step=4, ncols=4）→ +12h..+24h を1枚、のようなページングが可能
#
# 依存
#  - matplotlib / cartopy（cartopyは関数内import）
#  - cfgrib / xarray
#  - module.utils.var_utils.get_var, module.utils.xr_utils.align_datasets_common
#
# 2025-08 改訂
# =============================================================================

from __future__ import annotations

import os
from typing import List, Tuple, Optional, Iterable

import cfgrib
import xarray as xr
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# フォント（Linux環境での無難な既定）
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]

from module.utils.var_utils import get_var
from module.utils.xr_utils import align_datasets_common

# Pillow は後段の合成ユーティリティで使用
from PIL import Image


# =============================================================================
# NO DATA パネル
# =============================================================================
def make_nodata_weather_panel(
    times: Iterable,
    save_path: str = "nodata_panel.jpg",
    title: str = "NO DATA",
    city_name: Optional[str] = None,
    dpi: int = 150,
) -> str:
    """
    データが無い/取得に失敗したときの「NO DATA」画像を出力。

    Parameters
    ----------
    times : Iterable
        期待していた時刻の配列（表示用）
    save_path : str
        出力パス
    title : str
        タイトル文字
    city_name : Optional[str]
        都市名（表示用）
    dpi : int
        保存時DPI

    Returns
    -------
    save_path : str
    """
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.axis("off")
    main_title = f"{title}  [{city_name}]" if city_name else title
    msg = f"{main_title}\n\nWeather data could not be retrieved.\n\n"
    msg += "\n".join([str(pd.Timestamp(t).strftime("%Y-%m-%d %H:%M")) for t in times])
    ax.text(0.5, 0.5, msg, fontsize=20, ha="center", va="center", wrap=True)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    print(f"[NO DATA panel] {save_path} exported.")
    return save_path


# =============================================================================
# cfgrib / xarray 安全 open
# =============================================================================
def open_isobaric_dataset(fname: str | xr.Dataset, hPa: Optional[int] = None) -> xr.Dataset:
    """
    等圧面（isobaricInhPa）を含む Dataset を安全に取得。
    - fname が xr.Dataset の場合はそのまま返す
    - cfgrib.open_datasets() を総当たりし、isobaricInhPa と step を含むものを選択
    - hPa を指定した場合はその層に sel して返す
    """
    if isinstance(fname, xr.Dataset):
        return fname

    print(f"[DEBUG] open_isobaric_dataset: fname={fname}, hPa={hPa}")
    try:
        dsets = cfgrib.open_datasets(fname)
    except Exception as e:
        raise RuntimeError(f"[ERROR] cfgrib open failed: {fname} - {e}")

    last = None
    for ds in dsets:
        levels = ds["isobaricInhPa"].values if "isobaricInhPa" in ds.variables else "N/A"
        print(f"[DEBUG]  candidate: dims={dict(ds.sizes)} has_isobaric={'isobaricInhPa' in ds} levels={levels}")
        if "isobaricInhPa" in ds.variables and "step" in ds.sizes:
            last = ds
            if hPa is not None:
                if int(hPa) in set(int(v) for v in ds["isobaricInhPa"].values):
                    return ds.sel(isobaricInhPa=int(hPa))
                else:
                    continue
            return ds

    if last is not None and hPa is not None:
        # 近い層にフォールバックしても良い場合はここで実装可（今回は厳格に失敗）
        pass

    raise RuntimeError(f"[ERROR] isobaricInhPa層データが見つかりません: {fname}")


def open_surface_dataset(fname: str | xr.Dataset) -> xr.Dataset:
    """
    地上データ（meanSea や heightAboveGround, stepType=instant など）を安全に取得。
    - cfgrib.open_datasets() を総当たりし、使えそうなものを優先順に返す
    """
    if isinstance(fname, xr.Dataset):
        return fname

    print(f"[DEBUG] open_surface_dataset: fname={fname}")
    try:
        dsets = cfgrib.open_datasets(fname)
    except Exception as e:
        raise RuntimeError(f"[ERROR] cfgrib open failed: {fname} - {e}")

    # 優先度：instant / meanSea / heightAboveGround あたりの“地上系”
    chosen = None
    for ds in dsets:
        step_type = ds["stepType"].values if "stepType" in ds.variables else "N/A"
        print(f"[DEBUG]  candidate: dims={dict(ds.sizes)} stepType={step_type}")
        # 緩く拾う（用途に応じて絞り込みたい場合は条件を強化）
        if "step" in ds.sizes:
            chosen = ds  # last good
            # 条件を満たすものが見つかったら即返す
            if ("typeOfLevel" in ds.attrs and ds.attrs["typeOfLevel"] in ("surface", "meanSea", "heightAboveGround")) or \
               ("heightAboveGround" in ds.variables) or ("meanSea" in ds.variables):
                return ds

    if chosen is not None:
        return chosen

    raise RuntimeError(f"[ERROR] 地上instant・10mデータが見つかりません: {fname}")


# =============================================================================
# 汎用・複数列パネル生成
# =============================================================================
def _to_2d_axes(axes) -> np.ndarray:
    """matplotlib の axes を常に (nrows, ncols) の配列に正規化"""
    if isinstance(axes, np.ndarray) and axes.ndim == 2:
        return axes
    if isinstance(axes, np.ndarray) and axes.ndim == 1:
        return axes.reshape(-1, 1)
    return np.atleast_2d(axes)


def make_universal_weather_panel(
    save_dir: str,
    panel_def: List[Tuple],        # [(plot_func, ds_or_dict, title), ...] 行の定義
    times,                         # 未使用（互換用）/ 時刻ラベルは init_time_str & step から生成
    init_time_str: str,            # "YYYYMMDD_UTCHH"
    city_name: str = "japan",
    ncols: int = 1,                # ★ 列数：0..(ncols-1) の step を横に並べる
    nrows: int = 6,
    extent: Optional[Tuple[float, float, float, float]] = None,
    dpi: int = 300,
    step: Optional[int] = None,    # None の場合は「列方向に 0..(ncols-1) step」を自動表示
    start_step: int = 0,           # ページング用途：開始 step（例: 4 & ncols=4 → +12h..+24h を1枚）
    title_prefix: Optional[str] = None,
    filename_tag: Optional[str] = None,
) -> List[str]:
    """
    行=変数、列=連続 step の “複数列パネル” を 1 枚で保存する。

    仕様:
      - panel_def は (plot_func, ds_or_dict, title) の配列（行方向に並ぶ）
      - ds が dict の場合は plot_func(ax, ds, step=col_step) で呼び出し
      - ds が xarray.DataArray / Dataset の場合は step を isel してから plot_func(ax, ds_step)
      - step=None のとき、列 index j の表示ステップは start_step + j
      - step が int のときは全列ともその step を表示（単一時刻を横に同じもの並べる用途）
    """
    import cartopy.crs as ccrs  # 関数内 import（環境によっては重いので遅延）

    os.makedirs(save_dir, exist_ok=True)
    panel_imgs: List[str] = []

    # 行数をパディング
    if len(panel_def) < nrows:
        panel_def = panel_def + [(None, None, "")] * (nrows - len(panel_def))

    # 図領域を用意
    fig_w = max(3 * ncols, 3)   # 1セル横 3inch 目安
    fig_h = max(3 * nrows, 3)   # 1セル縦 3inch 目安
    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(fig_w, fig_h),
        constrained_layout=True,
        subplot_kw=dict(projection=ccrs.PlateCarree()),
    )
    axes = _to_2d_axes(axes)

    # 描画コア
    for row, (plot_func, ds, title) in enumerate(panel_def):
        for col in range(ncols):
            ax = axes[row, col]

            # 列→表示する step を決定
            if step is None:
                col_step = start_step + col
            else:
                col_step = step  # 単一 step を全列に表示したい場合

            # extent
            if extent:
                ax.set_extent(extent, crs=ccrs.PlateCarree())

            if plot_func is None or ds is None:
                ax.axis("off")
                ax.set_title("" if plot_func is None else f"{title} (no data)", fontsize=8)
                continue

            # Data の取り出し（dictか xarray かで分岐）
            render_ok = True
            try:
                if isinstance(ds, dict):
                    # 汎用：plot_func(ax, ds, step=col_step) で受ける想定
                    plot_func(ax, ds, step=col_step)
                else:
                    # xarray（DataArray または Dataset）
                    if hasattr(ds, "sizes") and ("step" in ds.sizes):
                        if col_step >= ds.sizes["step"]:
                            render_ok = False
                        else:
                            ds_step = ds.isel(step=col_step)
                            plot_func(ax, ds_step)
                    else:
                        # step 無しデータ（地上 Instant など）
                        plot_func(ax, ds)
            except Exception as e:
                print(f"[WARN] パネル描画失敗: row={row} col={col} title={title} step={col_step} err={e}")
                render_ok = False

            # タイトル
            if render_ok:
                hrs = col_step * 3  # 3-hourly 前提
                ax.set_title(f"{title}\n(+{hrs}h)", fontsize=8)
            else:
                ax.axis("off")
                ax.set_title(f"{title} (no data)", fontsize=8)

    # 上部タイトル
    main_title = title_prefix or f"{city_name} 天気図パネル（{init_time_str}）"
    fig.suptitle(main_title, fontsize=14)

    # 保存
    tag = filename_tag or f"{init_time_str}"
    out_name = f"panel_{city_name}_{tag}.jpg"
    out_path = os.path.join(save_dir, out_name)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    print(f"[OK] パネル画像保存: {out_path}")
    panel_imgs.append(out_path)
    return panel_imgs


# =============================================================================
# 既存の縦長画像をあとで横に連結（必要なら）
# =============================================================================
def concat_images_2by2(img1_path: str, img2_path: str, out_path: str) -> str:
    """
    2枚の画像を横に合成して保存
    """
    imgs = [Image.open(img1_path), Image.open(img2_path)]
    widths, heights = zip(*(img.size for img in imgs))
    total_width = sum(widths)
    max_height = max(heights)
    new_img = Image.new("RGB", (total_width, max_height))
    x_offset = 0
    for img in imgs:
        new_img.paste(img, (x_offset, 0))
        x_offset += img.width
        img.close()
    new_img.save(out_path)
    new_img.close()
    return out_path


def concat_panel_images_horizontally(img_paths: List[str], out_path: str) -> Optional[str]:
    """
    パネル画像リスト img_paths（左→右）を2枚ずつ段階的に合成し、最終的に1枚の横長画像を作る。
    """
    if not img_paths:
        print("[WARN] 画像リストが空です")
        return None
    temp_imgs = img_paths[:]
    round_num = 1
    while len(temp_imgs) > 1:
        next_temp_imgs: List[str] = []
        for i in range(0, len(temp_imgs), 2):
            if i + 1 < len(temp_imgs):
                out_tmp = f"{out_path}_tmp_r{round_num}_{i//2}.jpg"
                concat_images_2by2(temp_imgs[i], temp_imgs[i + 1], out_tmp)
                # 元画像以外の一時ファイルは削除
                if temp_imgs[i] not in img_paths and os.path.exists(temp_imgs[i]):
                    os.remove(temp_imgs[i])
                if temp_imgs[i + 1] not in img_paths and os.path.exists(temp_imgs[i + 1]):
                    os.remove(temp_imgs[i + 1])
                next_temp_imgs.append(out_tmp)
            else:
                # 奇数枚はそのまま通過
                next_temp_imgs.append(temp_imgs[i])
        temp_imgs = next_temp_imgs
        round_num += 1

    # 最終1枚
    os.replace(temp_imgs[0], out_path)
    print(f"[OK] 横結合画像保存: {out_path}")
    return out_path

# =============================================================================
# 行=変数 × 列=時系列 の横長モザイク（タイル出力 → 最後に1枚JPG）
# =============================================================================
from typing import Sequence
from PIL import Image, ImageDraw, ImageFont

def render_core_rows_tiles_for_step(
    panel_def: list[tuple],
    *,
    titles_want: Sequence[str],     # 例: ["850", "700", "500", "地上"]
    step: int,
    extent=None,
    out_dir: str = "./tiles",
    dpi: int = 120,
    tile_size_inch: tuple[float, float] = (3.0, 3.0),  # 1タイルの図サイズ
    file_tag: str = "",                                  # 例: "fh03"
) -> list[str]:
    """
    指定 step の“行”（850/700/500/地上など）だけを抽出して、1行=1枚のJPGタイルに保存する。
    return: [tile_path(row0), tile_path(row1), ...]  (titles_wantの順)
    """
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    os.makedirs(out_dir, exist_ok=True)

    # タイトルで行を抽出（ゆるく部分一致）
    def _pick_idx_by_title():
        idx_list = []
        titles = [t for (_, _, t) in panel_def]
        for want in titles_want:
            w = str(want)
            cand = [i for i, t in enumerate(titles) if t and (w in t)]
            idx_list.append(cand[0] if cand else -1)
        return idx_list

    row_indices = _pick_idx_by_title()
    paths: list[str] = []

    for ridx, want in zip(row_indices, titles_want):
        if ridx < 0:
            # ダミーNO DATAを出す
            dummy = os.path.join(out_dir, f"tile_{file_tag}_{want}_nodata.jpg")
            fig, ax = plt.subplots(figsize=tile_size_inch)
            ax.axis("off")
            ax.text(0.5, 0.5, f"{want}\n(no data)", ha="center", va="center")
            fig.savefig(dummy, dpi=dpi, bbox_inches="tight")
            plt.close(fig)
            paths.append(dummy)
            continue

        plot_func, ds, title = panel_def[ridx]

        fig, ax = plt.subplots(
            figsize=tile_size_inch,
            subplot_kw=dict(projection=ccrs.PlateCarree())
        )
        if extent:
            ax.set_extent(extent, crs=ccrs.PlateCarree())

        ok = True
        try:
            if isinstance(ds, dict):
                plot_func(ax, ds, step=step)
            else:
                if hasattr(ds, "sizes") and ("step" in ds.sizes):
                    if step >= ds.sizes["step"]:
                        ok = False
                    else:
                        plot_func(ax, ds.isel(step=step))
                else:
                    plot_func(ax, ds)
        except Exception as e:
            print(f"[WARN] tile render failed: '{title}' step={step}: {e}")
            ok = False

        if ok:
            ax.set_title(f"{title} (+{step*3}h)", fontsize=8)
        else:
            ax.axis("off"); ax.set_title(f"{title} (no data)", fontsize=8)

        fname = f"tile_{file_tag}_{want}.jpg"
        fpath = os.path.join(out_dir, fname)
        fig.savefig(fpath, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        paths.append(fpath)

    return paths


def assemble_time_series_mosaic_jpg(
    *,
    rows_order: Sequence[str],          # 例: ["850","700","500","地上"]  (上からこの順)
    steps_order: Sequence[int],         # 例: [0,1,2,3,4,5,6,7,8,9,10]  (3h刻みstep)
    tiles_dir: str = "./tiles",         # 各runnerで出力したタイルが集まっている場所（artifact DL後）
    out_path: str = "./output/japan_timeseries_all.jpg",
    h_gap: int = 8,
    v_gap: int = 12,
    bg_rgb: tuple[int,int,int] = (255,255,255),
    add_header: str | None = None,      # 例: "JAPAN Panel 20250814 UTC00"
    header_px: int = 48,
) -> str:
    """
    「行=rows_order」「列=steps_order」でタイルを敷き詰めて最終1枚の横長JPGを作る。
    期待タイルの名前は: tiles/tile_fh{step*3:02}_{row}.jpg（推奨）
      ※file_tag は各runnerが render_core_rows_tiles_for_step で付ける値
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # すべてのタイルをロード（存在しないものはNot Foundプレースホルダ）
    grid: list[list[Image.Image]] = []
    W = H = None

    def _load_or_placeholder(p: str, want_size: tuple[int,int]|None):
        if os.path.exists(p):
            im = Image.open(p).convert("RGB")
        else:
            # プレースホルダ（グレー）
            im = Image.new("RGB", want_size or (400, 400), (230,230,230))
            d = ImageDraw.Draw(im)
            d.text((10,10), os.path.basename(p), fill=(80,80,80))
        if want_size and im.size != want_size:
            im = im.resize(want_size, Image.BILINEAR)
        return im

    # 1枚目のサイズを基準に揃える
    sample = None
    for st in steps_order:
        for row in rows_order:
            candidate = os.path.join(tiles_dir, f"tile_fh{st*3:02}_{row}.jpg")
            if os.path.exists(candidate):
                sample = Image.open(candidate).convert("RGB")
                break
        if sample:
            break
    base_size = sample.size if sample else (600, 600)

    for row in rows_order:
        row_imgs: list[Image.Image] = []
        for st in steps_order:
            p = os.path.join(tiles_dir, f"tile_fh{st*3:02}_{row}.jpg")
            row_imgs.append(_load_or_placeholder(p, base_size))
        grid.append(row_imgs)

    # キャンバスサイズ計算
    cols = len(steps_order)
    rows = len(rows_order)
    W = base_size[0]*cols + h_gap*(cols-1)
    H = base_size[1]*rows + v_gap*(rows-1)
    total_h = H + (header_px if add_header else 0)

    canvas = Image.new("RGB", (W, total_h), bg_rgb)
    y = header_px if add_header else 0

    # ヘッダ
    if add_header:
        d = ImageDraw.Draw(canvas)
        d.text((10, 10), add_header, fill=(30,30,30))

    # 貼り付け
    for r in range(rows):
        x = 0
        for c in range(cols):
            canvas.paste(grid[r][c], (x, y))
            x += base_size[0] + h_gap
        y += base_size[1] + v_gap

    canvas.save(out_path, quality=90, optimize=True)
    print(f"[OK] 横長最終JPG: {out_path}")
    return out_path



__all__ = [
    "make_nodata_weather_panel",
    "get_var",                     # var_utils 経由の利便性維持（任意）
    "align_datasets_common",
    "open_isobaric_dataset",
    "open_surface_dataset",
    "make_universal_weather_panel",
    "concat_panel_images_horizontally",
]
