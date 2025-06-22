# msm_prmsl_dl_plot.py
import os
import urllib.request
from datetime import datetime
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

def download_msm_lsurf_grib2(dt, base_dir="./data"):
    ymdh = dt.strftime("%Y%m%d%H")
    pattern = "MSM_GPV_Rjp_Lsurf"
    fname = f"Z__C_RJTD_{ymdh}0000_{pattern}_FH00-15_grib2.bin"
    url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/{dt.year}/{dt.strftime('%m')}/{dt.strftime('%d')}/{fname}"
    os.makedirs(base_dir, exist_ok=True)
    fpath = os.path.join(base_dir, fname)
    if not os.path.exists(fpath) or os.path.getsize(fpath) < 10000:
        print(f"[DL] {url}")
        try:
            urllib.request.urlretrieve(url, fpath)
            print(f"[OK] DL: {fpath}")
        except Exception as e:
            print(f"[NG] DL失敗: {e}")
            return None
    else:
        print(f"[SKIP] 既存: {fpath}")
    return fpath

def plot_prmsl_from_grib2(grib2_path, save_path="msm_prmsl_test.jpg"):
    ds = xr.open_dataset(grib2_path, engine="cfgrib", filter_by_keys={'stepType': 'instant'})
    print(ds)
    print("[VAR]", list(ds.data_vars))
    # step=0が初期時刻の予報値（3h先）を指すので、step軸を使う
    msl = ds["prmsl"].isel(step=0) / 100  # Pa→hPa
    lons = ds["longitude"]
    lats = ds["latitude"]

    fig = plt.figure(figsize=(9, 7))
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent([120, 150, 22, 48], crs=ccrs.PlateCarree())
    ax.coastlines(resolution="50m")
    cs = ax.contour(lons, lats, msl, levels=range(960, 1050, 4), colors='black')
    ax.clabel(cs, fmt="%.0f", fontsize=8)
    plt.title("MSM 地上気圧 (hPa) [step=0]")
    plt.savefig(save_path, dpi=150)
    plt.close()
    print(f"[OK] 保存: {save_path}")

if __name__ == "__main__":
    dt = datetime(2025, 6, 21, 0, 0, 0)
    grib2_path = download_msm_lsurf_grib2(dt)
    if grib2_path and os.path.exists(grib2_path):
        plot_prmsl_from_grib2(grib2_path, save_path="msm_prmsl_test.jpg")
    else:
        print("[FAIL] MSM GRIB2ファイルが取得できませんでした")
