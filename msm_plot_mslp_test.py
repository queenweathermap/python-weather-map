# msm_plot_mslp_test.py
# ==========================================
# MSM GPV GRIB2（地上気圧）簡易描画
# ==========================================

import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import os

# MSMの地上データGRIB2パスを指定
GRIB2_PATH = "./data/Z__C_RJTD_20240621000000_MSM_GPV_Rjp_Lsurf_FD0000-0100_grib2.bin"

# --- GRIB2ファイルをxarrayで開く ---
ds = xr.open_dataset(GRIB2_PATH, engine="cfgrib", filter_by_keys={'stepType': 'instant'})
print(ds)

# 変数一覧
print(ds.data_vars)

# "prmsl" = mean sea level pressure（Pa）
msl = ds["prmsl"].isel(step=0) / 100  # Pa→hPa
lons = ds["longitude"]
lats = ds["latitude"]
print(msl.shape)

# --- 描画 ---
fig = plt.figure(figsize=(9, 7))
ax = plt.axes(projection=ccrs.PlateCarree())
ax.set_extent([120, 150, 22, 48], crs=ccrs.PlateCarree())
ax.coastlines(resolution="50m")
cs = ax.contour(lons, lats, msl, levels=range(960, 1050, 4), colors='black')
ax.clabel(cs, fmt="%.0f", fontsize=8)
plt.title("MSM 地上気圧 (hPa)", fontname="IPAexGothic")
IMG_PATH = "msm_mslp_test.jpg"
plt.savefig(IMG_PATH, dpi=150)
plt.close()
print(f"[OK] 保存: {IMG_PATH}")
