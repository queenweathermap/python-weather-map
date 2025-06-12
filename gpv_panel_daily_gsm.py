# gpv_panel_daily_gsm.py
# ===============================================
# GSM天気図 6行×n列パネル生成スクリプト
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
plt.rcParams['font.family'] = 'IPAGothic'  # 日本語フォント指定
import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- サブモジュール読み込み（描画関数群など） ---
from gpv_downloader import download_gpv_all, grib2_to_nc
from module.gpv_plotter_gsm import (
    plot_300hpa_height_wind_gsm,
    plot_500hpa_vorticity_gsm,
    plot_700hpa_dindex_500hpa_temp_gsm,
    plot_850hpa_temp_wind_700hpa_w_gsm,
    plot_850hpa_thetae_stream_gsm,
    plot_925hpa_temp_wind_dindex_gsm,
    plot_surface_pressure_and_wind_gsm,
    plot_emagram_gsm_panel,
)
# --- ※Slack送信importは不要・完全削除 ---

print("==== GSMパネル処理開始 ====")


# =====================================================
# 汎用：地図に経緯度グリッド線を追加（各描画関数内で利用）
# =====================================================
def add_gridlines(ax):
    """Cartopy図にグリッド線・ラベルを追加"""
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

# =====================================================
# データ未取得時の「NO DATA」パネル生成
# =====================================================
def make_nodata_weather_panel(times, save_path):
    """NO DATAパネル画像（全白、NO DATAラベル入り）を生成して保存"""
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
    fig.suptitle("GPVデータ未取得（NO DATAパネル）", fontsize=16)
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f"[NO DATAパネル生成] {save_path}")

# =====================================================
# メイン：天気図パネル画像の生成（複数時刻×多段）
# =====================================================
def make_daily_weather_panel_multi_time(ds, times, save_path):
    """
    複数時刻のGSM天気図パネル（6行×n列）を一括描画・保存
    ds: xarray Dataset（GPVデータ）
    times: 対象時刻リスト
    save_path: 画像保存パス
    """
    ncols = len(times)
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(
        nrows=6, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )
    # 1次元 or 行数不足対策
    if axes.ndim == 1:
        axes = axes.reshape((6, 1))
    elif axes.shape[0] != 6:
        axes = axes.reshape((6, -1))

    # タイトル用：初期時刻や時差ラベルの準備
    init_time = pd.Timestamp(times[0])
    init_label = init_time.strftime('%Y%m%d %HUTC')
    col_labels, hh_labels = [], []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    # パネルごとに描画
    for col, time in enumerate(times):
        # データ有無判定
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
        # 時刻ラベル
        axes[5, col].text(
            0.5, -0.18,
            col_labels[col],
            fontsize=9,
            ha='center',
            va='top',
            transform=axes[5, col].transAxes
        )
    # 各パネルにグリッド線追加
    for ax in axes.flatten():
        add_gridlines(ax)
    # 全体タイトル
    fig.suptitle(
        f"GSM天気図パネル\nInit: {init_label} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )
    # 保存
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("画像ファイルの存在:", os.path.exists(save_path))

# ===============================
# 設定（データパターン名・保存先ディレクトリ等）
# ===============================
GSM_PATTERNS = [
    "GSM_GPV_Rjp_Gll0p1deg_L-pall_FD0000-0100_grib2.bin",
    "GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin",
]
BASE_DIR = "./data"

# ===============================
# メイン処理（直接実行時のみ動作）
# ===============================
# ===============================
# メイン処理（直接実行時のみ動作）
# ===============================
if __name__ == "__main__":
    import traceback, sys
    try:
        print("1. データダウンロード開始")
        downloaded = download_gpv_all(GSM_PATTERNS, base_dir=BASE_DIR)
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
        nc_l_pall = [p for p in nc_paths if "L-pall" in p][0]
        nc_lsurf  = [p for p in nc_paths if "Lsurf"  in p][0]
        print("nc_l_pall:", nc_l_pall, "nc_lsurf:", nc_lsurf)

        # 🔽 ここから修正ポイント
        ds_l_pall = xr.open_dataset(nc_l_pall, engine="netcdf4")
        ds_lsurf  = xr.open_dataset(nc_lsurf, engine="netcdf4")

        # time, latitude, longitude が揃っているかチェックし、ずれていたら合わせる
        for dim in ['time', 'latitude', 'longitude']:
            if dim in ds_l_pall and dim in ds_lsurf:
                # assign_coordsで強制的に同じ座標配列にする
                ds_lsurf = ds_lsurf.assign_coords({dim: ds_l_pall[dim]})

        ds = xr.merge([ds_l_pall, ds_lsurf])
        print("xr.merge OK")
        # 🔼 修正ポイントここまで

        times = ds.time.values[:12]
        print("times:", times)
        make_daily_weather_panel_multi_time(ds, times, "gsm_weather_map.jpg")
        print("画像生成完了")
        print("=== 完了 ===")
    except Exception as e:
        print("=== 重大エラー発生 ===")
        print(type(e), e)
        traceback.print_exc()
        sys.exit(1)
