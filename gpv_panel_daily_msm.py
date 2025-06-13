# gpv_panel_daily_msm.py
# ===============================================
# MSM天気図 6行×n列パネル生成スクリプト
# ===============================================

import os
import sys
import traceback
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'IPAGothic'
import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- サブモジュール ---
from gpv_downloader import download_gpv_all, grib2_to_nc
from module.utils.xr_utils import align_datasets_common
from module.gpv_plotter_msm import (
    plot_emagram_msm_panel,
    plot_500hpa_vorticity_msm,
    plot_700hpa_dindex_500hpa_temp_msm,
    plot_850hpa_temp_wind_700hpa_w_msm,
    plot_850hpa_thetae_stream_msm,
    plot_925hpa_temp_wind_dindex_msm,
    plot_surface_pressure_and_wind_msm,
)

def add_gridlines(ax):
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

def make_nodata_weather_panel(times, save_path):
    nrows, ncols = 6, max(1, len(times))
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize)
    # axesを強制的に2次元配列化
    if nrows == 1 and ncols == 1:
        axes = np.array([[axes]])
    elif nrows == 1 or ncols == 1:
        axes = np.atleast_2d(axes)
        if axes.shape[0] != nrows:  # (ncols, )の場合
            axes = axes.T
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


def make_daily_weather_panel_multi_time(ds, times, save_path):
    if times is None or len(times) == 0:
        print("timesが空です。NO DATAパネルを作成します")
        make_nodata_weather_panel([np.datetime64('now')], save_path)
        return
    ncols = len(times)
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(
        nrows=6, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )
    if axes.ndim == 1:
        axes = axes.reshape((6, 1))
    elif axes.shape[0] != 6:
        axes = axes.reshape((6, -1))
    init_time = pd.Timestamp(times[0])
    init_label = init_time.strftime('%Y%m%d %HUTC')
    col_labels, hh_labels = [], []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")
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
        dsi = ds.sel(time=time)  # ←ここで「その時刻のDataset」になっている
    
        # 各plot関数では「Dataset」でも「DataArray」でもOKなようにisinstanceで分岐
        plot_500hpa_vorticity_msm(axes[0, col], dsi)
        plot_700hpa_dindex_500hpa_temp_msm(axes[1, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_msm(axes[2, col], dsi)
        plot_850hpa_thetae_stream_msm(axes[3, col], dsi)
        plot_925hpa_temp_wind_dindex_msm(axes[4, col], dsi)
        plot_surface_pressure_and_wind_msm(axes[5, col], dsi)
        axes[5, col].text(
            0.5, -0.18,
            col_labels[col],
            fontsize=9,
            ha='center',
            va='top',
            transform=axes[5, col].transAxes
        )

    for ax in axes.flatten():
        add_gridlines(ax)
    fig.suptitle(
        f"MSM天気図パネル\nInit: {init_label} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("画像ファイルの存在:", os.path.exists(save_path))

MSM_PATTERNS = [
    "MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH18-33_grib2.bin",
    "MSM_GPV_Rjp_L-pall_FH36-39_grib2.bin",
]
BASE_DIR = "./data"

if __name__ == "__main__":
    try:
        print("1. MSM GPVデータのダウンロード＆変換")
        downloaded = download_gpv_all(MSM_PATTERNS, base_dir=BASE_DIR)
        print("downloaded:", downloaded)
        if not downloaded or len(downloaded) < 3:
            base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [base_time + pd.Timedelta(hours=3*i) for i in range(12)]
            make_nodata_weather_panel(times, "msm_panel_nodata.jpg")
            print("【ERROR】MSM GPVデータ未取得。NO DATAパネル生成")
            sys.exit(1)

        print("2. NetCDF変換開始")
        nc_paths = [grib2_to_nc(path) for path, _ in downloaded]
        print("nc_paths:", nc_paths)
        ds_list = [xr.open_dataset(nc) for nc in nc_paths]

        # --- 各ファイルの中身を詳細print
        for i, ds in enumerate(ds_list):
            print(f"--- ds_list[{i}] ---")
            print(ds)
            print("dims:", ds.dims)
            print("coords:", list(ds.coords))
            print("variables:", list(ds.variables))
            if "time" in ds.coords:
                print("time:", ds["time"].values)
            if "latitude" in ds.coords:
                print("latitude shape:", ds["latitude"].shape)
            if "longitude" in ds.coords:
                print("longitude shape:", ds["longitude"].shape)

        print("\n== merge前のds_listチェック完了 ==\n")

        # --- 一旦素のmergeで失敗チェック
        try:
            ds_raw = xr.merge(ds_list)
            print("xr.merge(ds_list) 1st try: OK")
            print(ds_raw)
        except Exception as e:
            print("[WARNING] xr.merge(ds_list)で失敗:", e)

        # ★ 座標軸揃え（共通化）
        ds_list_aligned = align_datasets_common(ds_list)
        for i, ds in enumerate(ds_list_aligned):
            print(f"--- ds_list_aligned[{i}] ---")
            print(ds)
            print("dims:", ds.dims)
            print("coords:", list(ds.coords))
            print("variables:", list(ds.variables))
            if "time" in ds.coords:
                print("time:", ds["time"].values)
            if "latitude" in ds.coords:
                print("latitude shape:", ds["latitude"].shape)
            if "longitude" in ds.coords:
                print("longitude shape:", ds["longitude"].shape)

        print("== align_datasets_common OK ==")

        ds = xr.merge(ds_list_aligned, compat="override")
        print("xr.merge OK")
        print(ds)
        print("ds.data_vars:", ds.data_vars)
        print("ds.variables:", list(ds.variables))
        print("ds.time.values:", ds.time.values)

        # --- times取得（上位12件/空チェック）
        times = ds.time.values[:12]
        print("times:", times)

        # --- パネル作成
        make_daily_weather_panel_multi_time(ds, times, "msm_weather_map.jpg")
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        sys.exit(1)
