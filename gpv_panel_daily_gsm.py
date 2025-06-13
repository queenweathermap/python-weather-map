# gpv_panel_daily_gsm.py
# ===============================================
# GSM天気図 6行×12列パネル生成スクリプト
#  - GPVデータの自動ダウンロード＆grib2→NetCDF変換
#  - 天気図画像の自動生成（複数時刻・パネル形式）
#  - GitHub Actions／ローカル双方で動作
#  - データ未取得時はNO DATAパネルを自動生成
#  - Slack送信はmain_weather_batch.py側に完全移譲
# ===============================================

import os
import sys
import traceback
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'IPAGothic'
import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- サブモジュール読み込み ---
from gpv_downloader import download_gpv_panel, grib2_to_nc, find_nearest_init, GPV_MIRROR_URLS, GSM_PATTERNS
from module.utils.xr_utils import align_datasets_common
from module.gpv_plotter_gsm import (
    plot_300hpa_height_wind_gsm,
    plot_500hpa_vorticity_gsm,
    plot_700hpa_dindex_500hpa_temp_gsm,
    plot_850hpa_temp_wind_700hpa_w_gsm,
    plot_850hpa_thetae_stream_gsm,
    plot_surface_pressure_and_wind_gsm,
)

print("==== GSMパネル処理開始 ====")


def add_gridlines(ax):
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

def make_nodata_weather_panel(times, save_path):
    nrows, ncols = 6, max(1, len(times))
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize)
    if nrows == 1 and ncols == 1:
        axes = np.array([[axes]])
    elif nrows == 1 or ncols == 1:
        axes = np.atleast_2d(axes)
        if axes.shape[0] != nrows:
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
    fig.suptitle("GSM GPVデータ未取得（NO DATAパネル）", fontsize=16)
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
        dsi = ds.sel(time=time)
        plot_300hpa_height_wind_gsm(axes[0, col], dsi)
        plot_500hpa_vorticity_gsm(axes[1, col], dsi)
        plot_700hpa_dindex_500hpa_temp_gsm(axes[2, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_gsm(axes[3, col], dsi)
        plot_850hpa_thetae_stream_gsm(axes[4, col], dsi)
        plot_surface_pressure_and_wind_gsm(axes[5, col], dsi)
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
        f"GSM天気図パネル\nInit: {init_label} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("画像ファイルの存在:", os.path.exists(save_path))


BASE_DIR = "./data"
ncols = 12

if __name__ == "__main__":
    try:
        print("1. データダウンロード開始")
        # 直近のイニシャル時刻を探して指定（12, 0, 18, 6UTC優先）
        init_dt = find_nearest_init([12, 0, 18, 6])
        print("init_dt:", init_dt)
        downloaded = download_gpv_panel(GSM_PATTERNS, BASE_DIR, init_dt, GPV_MIRROR_URLS, ncols=ncols)
        print("downloaded:", downloaded)
        if not downloaded or len(downloaded) < 2:
            print("NO DATA: downloaded is None or <2")
            base_time = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
            times = [base_time + pd.Timedelta(hours=3*i) for i in range(12)]
            make_nodata_weather_panel(times, "gsm_panel_nodata.jpg")
            print("【ERROR】GPVファイル未取得。NO DATAパネル送信処理へ…")
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
                print("time dtype:", ds["time"].dtype)
            if "latitude" in ds.coords:
                print("latitude shape:", ds["latitude"].shape)
            if "longitude" in ds.coords:
                print("longitude shape:", ds["longitude"].shape)

        print("\n== merge前のds_listチェック完了 ==\n")

        # --- timeのdtypeを明示的に統一
        for i, ds in enumerate(ds_list):
            if ds["time"].dtype != "datetime64[ns]":
                ds = ds.assign_coords(time=ds["time"].astype("datetime64[ns]"))
                ds_list[i] = ds
                print(f"[修正] ds_list[{i}]のtimeをdatetime64[ns]に揃えました")

        # --- merge (join="outer"を明示)
        ds_list_aligned = align_datasets_common(ds_list)
        for i, ds in enumerate(ds_list_aligned):
            print(f"--- ds_list_aligned[{i}] ---")
            print(ds)
            print("dims:", ds.dims)
            print("coords:", list(ds.coords))
            print("variables:", list(ds.variables))
            if "time" in ds.coords:
                print("time:", ds["time"].values)
                print("time dtype:", ds["time"].dtype)
            if "latitude" in ds.coords:
                print("latitude shape:", ds["latitude"].shape)
            if "longitude" in ds.coords:
                print("longitude shape:", ds["longitude"].shape)

        print("== align_datasets_common OK ==")

        ds = xr.merge(ds_list_aligned, compat="override", join="outer")
        print("xr.merge OK")
        print(ds)
        print("ds.data_vars:", ds.data_vars)
        print("ds.variables:", list(ds.variables))
        print("ds.time dtype:", ds.time.dtype)
        print("ds.time.values:", ds.time.values)
        print("len(ds.time):", len(ds.time.values))

        # --- times取得（上位12件/空チェック）
        times = ds.time.values[:12]
        print("times:", times)

        # --- パネル作成
        make_daily_weather_panel_multi_time(ds, times, "gsm_weather_map.jpg")
        print("画像生成完了")
        print("=== 完了 ===")

    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        sys.exit(1)
