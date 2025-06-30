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
    # すでにxarray.Datasetならそのまま返す
    if isinstance(fname, xr.Dataset):
        return fname
    # ここから先はファイルパス（str）のみ通す
    for ds in cfgrib.open_datasets(fname):
        if "isobaricInhPa" in ds.variables and "step" in ds.sizes:
            if hPa is not None:
                if hPa in ds["isobaricInhPa"]:
                    return ds.sel(isobaricInhPa=hPa)
                else:
                    continue
            return ds
    raise RuntimeError(f"[ERROR] isobaricInhPa層データが見つかりません: {fname}")



def open_surface_dataset(fname):
    import cfgrib
    import xarray as xr
    if isinstance(fname, xr.Dataset):
        return fname
    for ds in cfgrib.open_datasets(fname):
        try:
            # stepTypeがinstant かつ heightAboveGround==10 だけ返す
            if (
                "stepType" in ds.variables
                and hasattr(ds, "stepType")
                and (getattr(ds, "stepType", None) == "instant"
                     or (hasattr(ds.stepType, "values") and all(ds.stepType.values == "instant")))
                and "heightAboveGround" in ds.variables
                and np.all(ds["heightAboveGround"].values == 10.0)
            ):
                return ds
        except Exception as e:
            print(f"[cfgrib skip] {e}")
            continue
    # fallback: cfgribフィルタで指定
    try:
        ds = xr.open_dataset(
            fname,
            engine="cfgrib",
            filter_by_keys={"stepType": "instant", "typeOfLevel": "heightAboveGround", "heightAboveGround": 10}
        )
        return ds
    except Exception:
        pass
    raise RuntimeError(f"[ERROR] 地上instant・10mデータが見つかりません: {fname}")



def make_universal_weather_panel(
    save_dir,
    panel_def,
    times,
    init_time_str,
    city_name="japan",
    ncols=8, nrows=6,   # ←8列6段
    extent=None,
    dpi=300
):
    """
    8列×6段（合計48コマ）の1枚パネル画像を生成
    ファイル右上にイニシャル時刻入りのファイル名
    """
    import cartopy.crs as ccrs
    import matplotlib.pyplot as plt
    os.makedirs(save_dir, exist_ok=True)
    panel_imgs = []

    # 行数補完
    if len(panel_def) < nrows:
        for _ in range(nrows - len(panel_def)):
            panel_def.append((None, None, ""))

    # --- パネル描画 ---
    fig, axes = plt.subplots(
        nrows=nrows, ncols=ncols,
        figsize=(ncols*3, nrows*3),
        constrained_layout=True,
        subplot_kw=dict(projection=ccrs.PlateCarree())
    )

    for row, (plot_func, ds, title) in enumerate(panel_def):
        for col in range(ncols):
            step = col
            ax = axes[row, col]
            if extent:
                ax.set_extent(extent, crs=ccrs.PlateCarree())
            if plot_func is None or ds is None:
                ax.axis("off")
                ax.set_title("")
                continue
            try:
                ds_step = ds.isel(step=step) if "step" in ds.sizes else ds
                plot_func(ax, ds_step)
                # 各コマのタイトル（不要なら空文字で）
                ax.set_title(f"{title}\n(+{step*3}h)", fontsize=7)
            except Exception as e:
                print(f"[WARN] パネル描画失敗: {title} {e}")
                ax.axis("off")
                ax.set_title(f"{title} (error)", fontsize=7)

    # ヘッダ・タイトルなし（要件どおり）
    # 右上にイニシャル時刻付きファイル名
    fig.text(0.99, 0.99, f"{city_name}_{init_time_str}", fontsize=10,
             ha="right", va="top", alpha=0.8, color="gray")

    # ファイル名例: panel_japan_20240701_00UTC.jpg
    out_name = f"panel_{city_name}_{init_time_str}.jpg"
    out_path = os.path.join(save_dir, out_name)
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    panel_imgs.append(out_path)
    return panel_imgs



__all__ = [
    "make_nodata_weather_panel",
    "get_lon_lat",
    "align_datasets_common",
    "open_isobaric_dataset",
    "open_surface_dataset",
    "make_universal_weather_panel"
]
