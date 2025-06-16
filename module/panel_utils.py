# ===============================================
# module/panel_utils.py
# 天気図パネル作成ユーティリティ（GSM/MSM/局地共通／全世界仕様）
# 2025-06-18 by ChatGPT
# -----------------------------------------------
# ・GSM/MSM/任意ローカルパネルの可視化パネルを生成する各種関数群
# ・NO DATA画像もグローバル英語化
# ・地図プロットの共通機能や、ラベル・メタ情報自動化対応
# ・多段構成やカスタムラベルにも柔軟対応
# ===============================================

import os
import numpy as np
import pandas as pd
import xarray as xr

import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

from module.utils.xr_utils import align_datasets_common

def make_nodata_weather_panel(
    times, 
    save_path="nodata_panel.jpg", 
    title="NO DATA", 
    city_name=None
):
    """
    Generate a NO DATA panel image for missing or failed data downloads.
    - times: list of forecast datetimes to display (for context)
    - save_path: Output image filename
    - title: Panel main title (default: "NO DATA")
    - city_name: (optional) City/region label to show (e.g. "Akita City")
    """
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.axis("off")

    if city_name:
        main_title = f"{title}  [{city_name}]"
    else:
        main_title = title

    msg = f"{main_title}\n\nWeather data could not be retrieved.\n\n"
    msg += "\n".join([str(pd.Timestamp(t).strftime("%Y-%m-%d %H:%M")) for t in times])
    ax.text(0.5, 0.5, msg, fontsize=20, ha="center", va="center", wrap=True)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[NO DATA panel] {save_path} exported.")


def make_local_weather_panel(
    ds, times, save_path,
    pin_lat, pin_lon, city_name,
    lat_range=None, lon_range=None,    # Optionally restrict the map area
    plot_func_list=None,
    nrows=6, ncols=12
):
    """
    Generate a local weather panel (with emagram) for a specified city/point.
    - ds: xarray.Dataset (forecast data, all times/levels included)
    - times: time list for panels
    - save_path: output image filename
    - pin_lat, pin_lon: point coordinates for emagram
    - city_name: str
    - lat_range, lon_range: tuple or list (min, max) for restricted region (optional)
    - plot_func_list: [func, ...] (first = emagram, others for map)
    - nrows, ncols: panel grid
    """
    import numpy as np
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs

    fig = plt.figure(figsize=(ncols * 2.5, nrows * 3.5))
    axes = np.empty((nrows, ncols), dtype=object)
    for row in range(1, nrows):
        for col in range(ncols):
            axes[row, col] = fig.add_subplot(nrows, ncols, row * ncols + col + 1, projection=ccrs.PlateCarree())

    # Prepare time labels
    init_time = pd.Timestamp(times[0])
    col_labels, hh_labels = [], []
    for time in times:
        t = pd.Timestamp(time)
        hour_diff = int((t - init_time).total_seconds() // 3600)
        label = f"{t.strftime('%Y%m%d %HUTC')} (+" + f"{hour_diff:02d}h)"
        col_labels.append(label)
        hh_labels.append(f"+{hour_diff:02d}")

    # Draw each time slot
    for col, time in enumerate(times):
        if pd.to_datetime(time) not in pd.to_datetime(ds.time.values):
            for row in range(nrows):
                ax = axes[row, col] if row > 0 else None
                if ax is not None:
                    ax.set_facecolor("white")
                    ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, color="gray", transform=ax.transAxes)
            continue

        # Pinpoint for emagram
        dsi_point = ds.sel(latitude=pin_lat, longitude=pin_lon, time=time, method='nearest')
        if plot_func_list:
            plot_func_list[0](fig, col, dsi_point, pin_lat, pin_lon, city_name, nrows, ncols)
        # Region selection for city
        if lat_range and lon_range:
            dsi = ds.sel(
                latitude=slice(*lat_range),
                longitude=slice(*lon_range),
                time=time
            )
        else:
            dsi = ds.sel(time=time)
        # Map panels for all but first row
        if plot_func_list:
            for row, func in enumerate(plot_func_list[1:], 1):
                func(axes[row, col], dsi)

    for row in range(1, nrows):
        for col in range(ncols):
            ax = axes[row, col]
            gl = ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
            gl.top_labels = False
            gl.right_labels = False

    # English title, globally sharable!
    fig.suptitle(
        f"[{city_name} Local] Weather Panel (incl. Emagram)\nInit: {init_time.strftime('%Y%m%d %HUTC')} | Forecasts: {', '.join(hh_labels)}",
        fontsize=12, y=1.02
    )
    plt.savefig(save_path, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("File exported:", os.path.exists(save_path))

def make_daily_weather_panel_multi_time(ds, times, save_path="weather_panel.jpg", plot_func_list=None, nrows=6, ncols=12):
    """
    Draw a multi-time, multi-row weather panel for a given day.
    - ds: xarray.Dataset
    - times: list of datetimes to plot
    - save_path: output image filename
    - plot_func_list: [func, ...] for each row (or column)
    - nrows, ncols: grid size
    """
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 2.5, nrows * 2.2), constrained_layout=True)
    axes = axes.flatten() if isinstance(axes, np.ndarray) else [axes]

    for idx, t in enumerate(times):
        ax = axes[idx]
        ax.set_axis_off()
        # If plot function available, draw panel; otherwise, gray "NO DATA"
        if plot_func_list and idx < len(plot_func_list):
            try:
                plot_func_list[idx](ax, ds, t)
            except Exception as e:
                ax.text(0.5, 0.5, "Plot Error", fontsize=10, ha="center", va="center")
        else:
            ax.set_facecolor("lightgray")
            ax.text(0.5, 0.5, "NO DATA", fontsize=16, ha="center", va="center")
        ax.set_title(str(t))

    # Hide unused panels
    for i in range(len(times), len(axes)):
        axes[i].set_axis_off()
    fig.suptitle("Weather Panel", fontsize=22)
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[Weather Panel] {save_path} exported.")

# --- 公開関数リストを明示 ---
__all__ = [
    "make_nodata_weather_panel",
    "make_local_weather_panel",
    "make_daily_weather_panel_multi_time",
    "align_datasets_common",
]
