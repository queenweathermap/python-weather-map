# gpv_downloader_and_plot.py
# ===============================================
# JMA GPV GSM/MSM データ自動ダウンロード＆GRIB2直読み＆天気図描画
# NetCDF変換は不要・cfgribで直接可視化
# 2025-06-21 by ChatGPT
# ===============================================

import os
import requests
import xarray as xr
import cartopy.crs as ccrs
import matplotlib.pyplot as plt

GPV_URL_BASE = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"

def download_gpv_gsm_lsurf(yyyymmddhh, out_dir="./data"):
    y, m, d, h = yyyymmddhh[:4], yyyymmddhh[4:6], yyyymmddhh[6:8], yyyymmddhh[8:10]
    fname = f"Z__C_RJTD_{yyyymmddhh}0000_GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin"
    url = f"{GPV_URL_BASE}/{y}/{m}/{d}/{fname}"
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, fname)
    if not os.path.exists(path) or os.path.getsize(path) < 100000:
        print("[DL]", url)
        resp = requests.get(url)
        if resp.status_code == 200:
            with open(path, "wb") as f:
                f.write(resp.content)
            print("[OK] Downloaded:", path)
        else:
            print("[NG] Download failed", url)
            return None
    else:
        print("[SKIP] Already exists:", path)
    return path

def plot_gpv_surface(grib_path, save_path="weather_map.jpg"):
    # cfgribでGRIB2を直接読み込む
    ds = xr.open_dataset(grib_path, engine="cfgrib")
    print("[INFO] Variables:", list(ds.data_vars))
    # Mean sea level pressure（hPa単位に変換されていることが多い）
    if 'msl' in ds:
        mslp = ds['msl'].isel(time=0) / 100.0  # Pa→hPa
    else:
        raise ValueError("msl (sea level pressure) がありません")
    # 1時間降水量
    prec_name = next((v for v in ds.data_vars if 'prec' in v or 'tp' in v), None)
    if prec_name is None:
        print("[WARN] 降水量フィールドが見つかりません")
        prec = None
    else:
        prec = ds[prec_name].isel(time=0)
    lons = ds['longitude']; lats = ds['latitude']
    # --- 可視化 ---
    fig = plt.figure(figsize=(9,8))
    ax = plt.subplot(1,1,1, projection=ccrs.PlateCarree())
    ax.set_extent([122,150,22,48], crs=ccrs.PlateCarree())
    ax.coastlines("50m")
    # 降水量塗りつぶし
    if prec is not None:
        c = ax.contourf(lons, lats, prec, levels=[1,5,10,20,50], alpha=0.7)
        plt.colorbar(c, ax=ax, shrink=0.8, label="Precip (mm/h)")
    # 等圧線
    cs = ax.contour(lons, lats, mslp, levels=range(int(mslp.min()), int(mslp.max())+1, 4), colors='k')
    ax.clabel(cs, fmt="%d", fontsize=8)
    plt.title("GSM GPV Mean Sea Level Pressure & Precip (1h)")
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    print("[OK] Saved:", save_path)

if __name__ == "__main__":
    yyyymmddhh = "2024062000"  # テスト用: 2024/06/20 00UTC（データあり）
    grib_path = download_gpv_gsm_lsurf(yyyymmddhh)
    if grib_path:
        plot_gpv_surface(grib_path, save_path="gsm_surface_map.jpg")
