# ===============================
# GSM用：5行×任意列パネル作成モジュール
# ===============================
import sys
import os
# この2行をスクリプトの一番最初に追加！
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import pandas as pd
from pathlib import Path

# ここは「from module.モジュール名」でOK！
from module.gpv_plotter_gsm import (
    plot_300hpa_height_wind,
    plot_700hpa_temp_rh,
    plot_850hpa_temp_wind_w,
    plot_850hpa_thetae_stream,
    plot_surface_pressure_and_wind,
)



# ===============================
# 経度・緯度線追加関数（全パネル一括）
# ===============================
def add_gridlines(ax):
    """
    サブプロットaxに緯度経度グリッド線を追加
    """
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    return gl

# ===============================
# GSM用：5行×n列パネル作成メイン関数
# ===============================
def make_daily_weather_panel_multi_time(ds, times, save_path):
    """
    1日n時刻×5要素のパネルを描画し、1枚画像で保存
    """
    ncols = len(times)
    figsize = (4 * ncols, 18)

    fig, axes = plt.subplots(
        nrows=5, ncols=ncols, figsize=figsize,
        subplot_kw={'projection': ccrs.PlateCarree()},
        constrained_layout=True
    )
    import numpy as np
    if axes.ndim == 1:
        axes = axes.reshape((5, 1))
    elif axes.shape[0] != 5:
        axes = axes.reshape((5, -1))

    # --- 初期時刻＆ラベル準備 ---
    init_time = pd.Timestamp(times[0])
    init_label = init_time.strftime('%Y%m%d %HUTC')
    col_labels = []
    hh_labels = []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    # --- 各パネル描画 ---
    for col, time in enumerate(times):
        dsi = ds.sel(time=time)
        plot_300hpa_height_wind(axes[0, col], dsi)
        plot_700hpa_temp_rh(axes[1, col], dsi)
        plot_850hpa_temp_wind_w(axes[2, col], dsi)
        plot_850hpa_thetae_stream(axes[3, col], dsi)
        plot_surface_pressure_and_wind(axes[4, col], dsi)

        # 5段目の下にだけ「時刻+経過時間」ラベルを追加
        axes[4, col].text(
            0.5, -0.18,
            col_labels[col],
            fontsize=9,
            ha='center',
            va='top',
            transform=axes[4, col].transAxes
        )

    # --- 全パネル一括で緯度・経度線追加 ---
    for ax in axes.flatten():
        add_gridlines(ax)

    # --- パネル全体タイトル ---
    fig.suptitle(
        f"GSM天気図パネル\nInit: {init_label} | Forecasts: {', '.join(hh_labels)}",
        fontsize=11, y=1.04
    )

    # --- 画像保存 ---
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
