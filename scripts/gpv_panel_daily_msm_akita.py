# scripts/gpv_panel_local_msm_akita.py
# ========================================================
# MSM秋田局地天気図パネル（6段×12列）＋Slack自動通知
# - 秋田エリアの高解像度パネルを12時刻（3時間ごと）出力
# - 6段目に秋田エマグラム（MSM予想値）を埋め込む
# - すべてGitHub Actions等サーバー運用を前提
# ========================================================

import os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

# 日本語表示（サーバーでも読めるフォントに調整可）
plt.rcParams['font.family'] = 'IPAGothic'

import cartopy.crs as ccrs
import pandas as pd
import xarray as xr

# --- MSM GPVデータ取得・変換用ユーティリティ ---
from scripts.gpv_downloader import download_msm_gpv, grib2_to_nc

# --- MSM各種パネル描画関数 ---
from module.gpv_plotter_msm import (
    plot_700hpa_dindex_500hpa_temp_msm,   # 700hPa湿数・500hPa温度
    plot_850hpa_temp_wind_700hpa_w_msm,   # 850hPa温度・風・鉛直流
    plot_850hpa_thetae_stream_msm,        # 850hPa相当温位
    plot_925hpa_temp_wind_dindex_msm,     # 925hPa温度・風・湿数
    plot_surface_pressure_and_wind_msm,   # 地上
    plot_emagram_msm,                     # 秋田エマグラム（MSM予想値）
)
# --- Slack送信用 ---
from module.slack_utils import send_file_to_slack

# ========================================================
# 秋田局地範囲の緯度・経度（必要なら微調整可）
# パネル5段まではエリア拡大図、6段目は秋田ピンポイントのエマグラム
# ========================================================
AKITA_LAT_RANGE = (38.8, 40.8)
AKITA_LON_RANGE = (139.2, 141.0)
AKITA_PIN_LAT = 39.72
AKITA_PIN_LON = 140.10

def add_gridlines(ax):
    """
    各サブプロットaxに緯度経度グリッド線を追加
    """
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

def make_local_weather_panel(ds, times, save_path):
    """
    秋田局地パネル（6段×12列）の作成・保存・Slack送信
    ds: xarray Dataset（MSM GPVデータ）
    times: 3時間ごとの12時刻（datetime64配列 or list）
    save_path: 保存ファイル名
    """
    ncols = len(times)
    nrows = 6
    figsize = (4 * ncols, 21)
    fig, axes = plt.subplots(
        nrows=nrows, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )

    # --- 初期時刻・経過ラベル生成 ---
    init_time = pd.Timestamp(times[0])
    col_labels = []
    hh_labels = []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    # --- 各時刻・各段パネル描画 ---
    for col, time in enumerate(times):
        # 1〜5段目: 秋田周辺の水平断面
        dsi = ds.sel(
            lat=slice(AKITA_LAT_RANGE[0], AKITA_LAT_RANGE[1]),
            lon=slice(AKITA_LON_RANGE[0], AKITA_LON_RANGE[1]),
            time=time
        )
        plot_700hpa_dindex_500hpa_temp_msm(axes[0, col], dsi)
        plot_850hpa_temp_wind_700hpa_w_msm(axes[1, col], dsi)
        plot_850hpa_thetae_stream_msm(axes[2, col], dsi)
        plot_925hpa_temp_wind_dindex_msm(axes[3, col], dsi)
        plot_surface_pressure_and_wind_msm(axes[4, col], dsi)

        # 6段目: 秋田ピンポイント（緯度経度指定）のエマグラム
        dsi_point = ds.sel(
            lat=AKITA_PIN_LAT, lon=AKITA_PIN_LON, time=time, method='nearest'
        )
        # エマグラムは投影不要（普通のaxがほしい）
        # Cartopy Axesのまま描画する場合、内部でgca置き換え/ax.clear()して2重描画に注意
        # ⇒一度ax.cla()でリセットし通常matplotlib軸として再利用
        ax_emagram = axes[5, col]
        ax_emagram.cla()  # 既存カートピープロジェクションをクリア
        plot_emagram_msm(ax_emagram, dsi_point,
                         city_lat=AKITA_PIN_LAT, city_lon=AKITA_PIN_LON, city_name="秋田")

        # 6段目に時刻ラベル
        ax_emagram.text(
            0.5, -0.18,
            col_labels[col],
            fontsize=9,
            ha='center',
            va='top',
            transform=ax_emagram.transAxes
        )

    # --- 全パネルにグリッド線を追加 ---
    for row in range(5):  # 1〜5段目のみ地図グリッド
        for col in range(ncols):
            add_gridlines(axes[row, col])
    # 6段目はエマグラムなのでグリッド不要

    # --- パネルタイトル ---
    fig.suptitle(
        f"【秋田局地版・MSM】天気図パネル（エマグラム含む）\nInit: {init_time.strftime('%Y%m%d %HUTC')} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )

    # --- 画像保存 ---
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)

    # --- Slack送信 ---
    print("画像ファイルの存在:", os.path.exists(save_path))
    print(">>> Slack送信直前です")
    try:
        send_file_to_slack(save_path, channel="C08988S0SRY")
    except Exception as e:
        print("Slack送信エラー:", e)

# ========================================================
# メイン処理（GitHub Actions/バッチ運用前提）
# ========================================================
if __name__ == "__main__":
    # --- 1. MSM GPVデータの自動取得＆NetCDF変換 ---
    grib2_path, init_time = download_msm_gpv()
    nc_path = grib2_to_nc(grib2_path)
    ds = xr.open_dataset(nc_path)
    # --- 2. 12時刻分のリスト作成（例: 3時間ごとx12本）---
    times = ds.time.values[:12]
    # --- 3. パネル作成＆Slack送信 ---
    print("==== パネル作成 ====")
    make_local_weather_panel(ds, times, "akita_local_msm_map.jpg")
    print("==== 完了 ====")
    print("正常終了")
