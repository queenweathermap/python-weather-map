# ===============================================
# module/panel_utils.py
# パネル可視化・NO DATA生成など可視化ユーティリティ
# ===============================================
import os
import cfgrib
import xarray as xr
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
    fig.savefig(save_path, bbox_inches="tight", dpi=150)
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

def open_isobaric_dataset(fname, hPa=None):
    """
    指定GRIB2ファイルから isobaricInhPa（気圧面）層を優先的に読み込む。
    hPaを指定すると、その気圧面のみ抽出。
    """
    for ds in cfgrib.open_datasets(fname):
        if "isobaricInhPa" in ds.variables and "step" in ds.dims:
            if hPa is not None:
                if hPa in ds["isobaricInhPa"]:
                    return ds.sel(isobaricInhPa=hPa)
                else:
                    continue
            return ds
    raise RuntimeError(f"[ERROR] isobaricInhPa層データが見つかりません: {fname}")

def open_surface_dataset(fname):
    """
    指定GRIB2ファイルから地上値（stepType="instant"）のデータセットを優先して取得
    """
    for ds in cfgrib.open_datasets(fname):
        try:
            if ("stepType" in ds.variables and
                hasattr(ds, "stepType") and
                (getattr(ds, "stepType", None) == "instant" or
                 (hasattr(ds.stepType, "values") and
                  all(ds.stepType.values == "instant")))):
                return ds
        except Exception:
            pass
    try:
        ds = xr.open_dataset(fname, engine="cfgrib", filter_by_keys={"stepType": "instant"})
        return ds
    except Exception:
        pass
    raise RuntimeError(f"[ERROR] 地上instantデータが見つかりません: {fname}")

# --- 新・共通パネル描画関数 ---
def make_universal_weather_panel(
    save_dir,
    panel_def,
    times,
    base_title,
    city_name="japan",
    ncols=4, nrows=7, npages=4,
    extent=None,
    dpi=200
):
    """
    7段×4列×4ページパネルを任意定義で一括生成。
    panel_def = [(plot_func, ds, title), ...] で7要素。
    plot_func=None, ds=None, title=""の箇所は空欄マスになる。
    """
    import cartopy.crs as ccrs
    os.makedirs(save_dir, exist_ok=True)
    panel_imgs = []
    for page in range(npages):
        fig, axes = plt.subplots(
            nrows=nrows, ncols=ncols,
            figsize=(ncols*3, nrows*3),
            constrained_layout=True,
            subplot_kw=dict(projection=ccrs.PlateCarree())
        )
        for row, (plot_func, ds, title) in enumerate(panel_def):
            for col in range(ncols):
                step = page * ncols + col
                ax = axes[row, col]
                if extent:
                    ax.set_extent(extent, crs=ccrs.PlateCarree())
                if plot_func is None or ds is None:
                    ax.axis("off")
                    ax.set_title("")
                    continue
                try:
                    ds_step = ds.isel(step=step) if "step" in ds.dims else ds
                    plot_func(ax, ds_step)
                    ax.set_title(f"{title} (+{step*3}h)")
                except Exception as e:
                    ax.axis("off")
                    ax.set_title(f"{title} (error)")
        fig.suptitle(f"{base_title}（{city_name}） page{page+1}", fontsize=18)
        out_name = f"panel_{city_name}_{base_title}_p{page+1}.jpg"
        out_path = os.path.join(save_dir, out_name)
        fig.savefig(out_path, dpi=dpi)
        plt.close(fig)
        panel_imgs.append(out_path)
    return panel_imgs

# --- 公開関数リストに追加 ---
__all__ = [
    "make_nodata_weather_panel",
    "get_lon_lat",
    "align_datasets_common",
    "open_isobaric_dataset",
    "open_surface_dataset",
    "make_universal_weather_panel"
]
