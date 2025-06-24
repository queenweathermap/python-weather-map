# ===============================================
# module/panel_utils.py
# パネル可視化・NO DATA生成など可視化ユーティリティ
# ===============================================
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']

from module.utils.var_utils import get_var
from module.utils.xr_utils import align_datasets_common

def make_nodata_weather_panel(
    times, 
    save_path="nodata_panel.jpg", 
    title="NO DATA", 
    city_name=None
):
    """
    Generate a NO DATA panel image for missing or failed data downloads.
    """
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.axis("off")
    main_title = f"{title}  [{city_name}]" if city_name else title
    msg = f"{main_title}\n\nWeather data could not be retrieved.\n\n"
    msg += "\n".join([str(pd.Timestamp(t).strftime("%Y-%m-%d %H:%M")) for t in times])
    ax.text(0.5, 0.5, msg, fontsize=20, ha="center", va="center", wrap=True)
    plt.tight_layout()
    fig.savefig(save_path, bbox_inches="tight")
    plt.close(fig)
    print(f"[NO DATA panel] {save_path} exported.")

def get_lon_lat(ds):
    """
    xarray.Datasetから2Dのlongitude/latitude配列を返す（2D保証）
    """
    lon = get_var(ds, "longitude")
    lat = get_var(ds, "latitude")
    if lon is None or lat is None:
        raise ValueError("longitude/latitudeがありません")
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    if lon.ndim == 1 and lat.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
    elif lon.ndim == 2 and lat.ndim == 2:
        lon2d, lat2d = lon, lat
    else:
        raise ValueError("緯度経度配列の形状が不正")
    return lon2d, lat2d

def make_local_weather_panel(
    ds, times, save_path,
    pin_lat, pin_lon, city_name,
    lat_range=None, lon_range=None,    # Optionally restrict the map area
    plot_func_list=None,
    nrows=6, ncols=12
):
    """
    Generate a local weather panel (with emagram) for a specified city/point.
    """
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

def make_lfm_panel(ds, times, save_path):
    # LFM用天気図パネル描画処理
    # ds: xarray.Dataset
    # times: list of datetime
    # save_path: 画像保存パス
    pass

# --- 公開関数リストを明示 ---
__all__ = [
    "make_nodata_weather_panel",
    "make_local_weather_panel",
    "make_daily_weather_panel_multi_time",
    "get_lon_lat",
    "align_datasets_common",
]
