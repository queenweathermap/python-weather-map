# scripts/gpv_panel_daily_msm.py
# ===============================================
# MSM天気図 6行×n列パネル生成スクリプト
#  - MSM GPVデータ自動ダウンロード＆grib2→NetCDF変換
#  - 複数時刻の天気図を6段×n列パネル形式で自動生成
#  - データ未取得時はNO DATAパネルを自動生成
#  - Slack送信はmain_weather_batch.pyで一括管理
# ===============================================

import sys
import os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'IPAGothic'  # 日本語フォント
import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- MSM用描画関数 ---
from scripts.gpv_downloader import download_gpv_all, grib2_to_nc
from module.gpv_plotter_msm import (
    plot_500hpa_vorticity_msm,
    plot_700hpa_dindex_500hpa_temp_msm,
    plot_850hpa_temp_wind_700hpa_w_msm,
    plot_850hpa_thetae_stream_msm,
    plot_925hpa_temp_wind_dindex_msm,
    plot_surface_pressure_and_wind_msm,
)
# --- Slack送信関連importは不要（完全削除） ---

# ===============================================
# MSMファイルパターンリスト・保存先
# ===============================================
MSM_PATTERNS = [
    "MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH18-33_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH36-39_grib2.bin",
    # 地上や他層も必要なら追加
]
BASE_DIR = "./data"

# ===============================================
# 汎用：地図グリッド線追加
# ===============================================
def add_gridlines(ax):
    """Cartopy地図に経緯度グリッド線＋ラベルを追加"""
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
    fig.suptitle("MSM GPVデータ未取得（NO DATAパネル）", fontsize=16)
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"[NO DATAパネル生成] {save_path}")

# ===============================================
# MSM天気図パネル画像生成（メイン関数）
# ===============================================
def make_daily_weather_panel_multi_time(ds, times, save_path):
    """
    MSM天気図6行×n列パネルを一括描画＆保存
    ds: xarray Dataset
    times: 描画時刻リスト
    save_path: 画像保存先
    """
    ncols = len(times)
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(
        nrows=6, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )
    # 1次元化or行数不足時のreshape対策
    if axes.ndim == 1:
        axes = axes.reshape((6, 1))
    elif axes.shape[0] != 6:
        axes = axes.reshape((6, -1))

    # タイトル＆ラベル作成
    init_time = pd.Timestamp(times[0])
    init_label = init_time.strftime('%Y%m%d %HUTC')
    col_labels, hh_labels = [], []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    # パネルごと描画
    for col, time in enumerate(times):
        if np.datetime64(time) not in ds.time.values:
            for row in range(6):
                ax = axes[row, col]
                ax.set_facecolor("white")
                for spine in ax.spines.values():
                    spine.set_edgecolor("gray")
                    spine.set_linewidth(1)
                ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
                ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, color="gray", transform=ax.transAxes)
            continue
        dsi = ds.sel(time=time)
        plot_500hpa_vorticity_msm(axes[0, col], dsi)
        plot_700hpa_dindex_500hpa_temp_msm(axes[1, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_msm(axes[2, col], dsi)
        plot_850hpa_thetae_stream_msm(axes[3, col], dsi)
        plot_925hpa_temp_wind_dindex_msm(axes[4, col], dsi)
        plot_surface_pressure_and_wind_msm(axes[5, col], dsi)
        # 時刻ラベル
        axes[5, col].text(
            0.5, -0.18,
            col_labels[col],
            fontsize=9,
            ha='center',
            va='top',
            transform=axes[5, col].transAxes
        )
    # グリッド線追加
    for ax in axes.flatten():
        add_gridlines(ax)
    # 全体タイトル
    fig.suptitle(
        f"MSM天気図パネル\nInit: {init_label} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )
    # 保存
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("画像ファイルの存在:", os.path.exists(save_path))

# ===============================================
# メイン処理
# ===============================================
if __name__ == "__main__":
    # 1. MSM GPVデータのダウンロード＆変換
    downloaded = download_gpv_all(MSM_PATTERNS, base_dir=BASE_DIR)
    if not downloaded or len(downloaded) < 3:
        # 必須ファイル欠如時はNO DATAパネルを出力して終了
        base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
        times = [base_time + pd.Timedelta(hours=3*i) for i in range(12)]
        make_nodata_weather_panel(times, "msm_panel_nodata.jpg")
        print("【ERROR】MSM GPVデータ未取得。NO DATAパネルを生成しました。")
        sys.exit(1)

    # 2. NetCDF結合
    nc_paths = [grib2_to_nc(path) for path, _ in downloaded]
    ds_list = [xr.open_dataset(nc) for nc in nc_paths]
    ds = xr.concat(ds_list, dim="time")

    # 3. 天気図パネル画像生成
    times = ds.time.values[:12]
    print("==== MSMパネル作成 ====")
    make_daily_weather_panel_multi_time(ds, times, "msm_weather_map.jpg")
    print("==== 完了 ====")
    print("正常終了")
