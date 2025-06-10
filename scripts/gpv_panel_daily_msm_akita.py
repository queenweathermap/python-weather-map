# scripts/gpv_panel_daily_msm_akita.py
# ========================================================
# MSM秋田局地天気図パネル（6段×12列）自動生成スクリプト
#  - MSM GPVデータ分割ダウンロード＆grib2→NetCDF変換
#  - 秋田局地6段×n列パネル天気図を一括生成
#  - データ未取得時はNO DATAパネル自動生成
#  - Slack送信はmain_weather_batch.pyに集約
# ========================================================

import sys
import os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'IPAGothic'  # 日本語フォント
import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- MSM用描画関数（秋田局地版） ---
from scripts.gpv_downloader import download_gpv_all, grib2_to_nc
from module.gpv_plotter_msm import (
    plot_emagram_msm,
    plot_700hpa_dindex_500hpa_temp_msm,
    plot_850hpa_temp_wind_700hpa_w_msm,
    plot_850hpa_thetae_stream_msm,
    plot_925hpa_temp_wind_dindex_msm,
    plot_surface_pressure_and_wind_msm,
)
# --- Slack送信import不要（完全削除） ---

# ===============================================
# MSM分割ファイルパターン（秋田局地も標準MSMを使用）
# ===============================================
MSM_PATTERNS = [
    "MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH18-33_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH36-39_grib2.bin",
]
BASE_DIR = "./data"
AKITA_LAT_RANGE = (38.8, 40.8)
AKITA_LON_RANGE = (139.2, 141.0)
AKITA_PIN_LAT = 39.72
AKITA_PIN_LON = 140.10

# ===============================================
# 汎用：地図グリッド線追加
# ===============================================
def add_gridlines(ax):
    """Cartopy図に経緯度グリッド線＋ラベルを追加"""
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

# ===============================================
# データ未取得時NO DATAパネル生成
# ===============================================
def make_nodata_weather_panel(times, save_path):
    """NO DATAパネル画像を生成し保存"""
    nrows, ncols = 6, len(times)
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize)
    for col in range(ncols):
        for row in range(nrows):
            ax = axes[row, col]
            ax.set_facecolor("white")
            for spine in ax.spines.values():
                spine.set_edgecolor("gray")
                spine.set_linewidth(1)
            ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
            ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, color="gray", transform=ax.transAxes)
    fig.suptitle("秋田局地 MSM GPVデータ未取得（NO DATAパネル）", fontsize=16)
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"[NO DATAパネル生成] {save_path}")

# ===============================================
# 秋田局地パネル画像生成メイン関数
# ===============================================
def make_local_weather_panel(ds, times, save_path):
    """
    秋田局地 MSM天気図6段×n列パネル生成
    ds: xarray Dataset
    times: 描画時刻リスト
    save_path: 画像保存先
    """
    ncols = len(times)
    nrows = 6
    figsize = (4 * ncols, 21)
    fig = plt.figure(figsize=figsize)
    axes = np.empty((nrows, ncols), dtype=object)
    
    # ラベル生成
    init_time = pd.Timestamp(times[0])
    col_labels, hh_labels = [], []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    # 2〜6段目: Cartopy投影Axes
    for row in range(1, nrows):
        for col in range(ncols):
            axes[row, col] = fig.add_subplot(nrows, ncols, row * ncols + col + 1, projection=ccrs.PlateCarree())

    # 各colの1段目：エマグラム
    for col, time in enumerate(times):
        # データ有無チェック
        if np.datetime64(time) not in ds.time.values:
            for row in range(nrows):
                ax = axes[row, col] if row > 0 else None  # row==0は下で生成
                if ax is not None:
                    ax.set_facecolor("white")
                    for spine in ax.spines.values():
                        spine.set_edgecolor("gray")
                        spine.set_linewidth(1)
                    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
                    ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, color="gray", transform=ax.transAxes)
            continue

        # 1行目：秋田ピンポイントのエマグラム
        dsi_point = ds.sel(
            latitude=AKITA_PIN_LAT, longitude=AKITA_PIN_LON, time=time, method='nearest'
        )
        plot_emagram_msm(
            fig,
            col,
            dsi_point,
            AKITA_PIN_LAT,
            AKITA_PIN_LON,
            "秋田",
            nrows=nrows,
            ncols=ncols
        )

        # 2〜6行目：秋田周辺の水平断面
        dsi = ds.sel(
            latitude=slice(AKITA_LAT_RANGE[0], AKITA_LAT_RANGE[1]),
            longitude=slice(AKITA_LON_RANGE[0], AKITA_LON_RANGE[1]),
            time=time
        )
        plot_700hpa_dindex_500hpa_temp_msm(axes[1, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_msm(axes[2, col], dsi)
        plot_850hpa_thetae_stream_msm(axes[3, col], dsi)
        plot_925hpa_temp_wind_dindex_msm(axes[4, col], dsi)
        plot_surface_pressure_and_wind_msm(axes[5, col], dsi)

    # 2〜6段目にグリッド線
    for row in range(1, nrows):
        for col in range(ncols):
            add_gridlines(axes[row, col])

    # 全体タイトル
    fig.suptitle(
        f"【秋田局地版・MSM】天気図パネル（エマグラム含む）\nInit: {init_time.strftime('%Y%m%d %HUTC')} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )
    # 保存
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("画像ファイルの存在:", os.path.exists(save_path))

# ===============================
# メイン処理
# ===============================
if __name__ == "__main__":
    # 1. MSM分割DL→NetCDF変換
    downloaded = download_gpv_all(MSM_PATTERNS, base_dir=BASE_DIR)
    if not downloaded or len(downloaded) < 3:
        base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
        times = [base_time + pd.Timedelta(hours=3*i) for i in range(12)]
        make_nodata_weather_panel(times, save_path="akita_panel_nodata.jpg")
        print("【ERROR】秋田局地 MSM GPVデータ未取得。NO DATAパネルを生成しました。")
        sys.exit(1)

    # 2. NetCDF変換・結合
    nc_paths = [grib2_to_nc(path) for path, _ in downloaded]
    ds_list = [xr.open_dataset(nc) for nc in nc_paths]
    ds = xr.concat(ds_list, dim="time")

    # 3. パネル作成
    times = ds.time.values[:12]
    print("==== 秋田局地 MSMパネル作成 ====")
    make_local_weather_panel(ds, times, "akita_local_msm_map.jpg")
    print("==== 完了 ====")
    print("正常終了")
