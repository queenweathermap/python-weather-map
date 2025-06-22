# msm_plot_mslp_test.py
# ==========================================
# MSM GPV GRIB2（地上気圧）簡易描画
# ==========================================

# msm_plot_mslp_test.py
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import os

GRIB2_PATH = "./data/Z__C_RJTD_20250621000000_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin"

if not os.path.exists(GRIB2_PATH):
    raise FileNotFoundError(f"{GRIB2_PATH} が見つかりません")

ds = xr.open_dataset(GRIB2_PATH, engine="cfgrib", filter_by_keys={'stepType': 'instant'})
print(ds)
print(ds.data_vars)

# prmsl or mslの確認（MSMはprmslが主）
msl = ds["prmsl"].isel(time=0) / 100  # Pa→hPa
lons = ds["longitude"]
lats = ds["latitude"]

fig = plt.figure(figsize=(9, 7))
ax = plt.axes(projection=ccrs.PlateCarree())
ax.set_extent([120, 150, 22, 48], crs=ccrs.PlateCarree())
ax.coastlines(resolution="50m")
cs = ax.contour(lons, lats, msl, levels=range(960, 1050, 4), colors='black')
ax.clabel(cs, fmt="%.0f", fontsize=8)
plt.title("MSM 地上気圧 (hPa)")
plt.savefig("msm_mslp_test.jpg", dpi=150)
plt.close()
print("[OK] msm_mslp_test.jpg 保存完了")
