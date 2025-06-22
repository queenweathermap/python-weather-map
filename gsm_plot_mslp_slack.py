import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import os

from module.drive_utils import upload_to_drive
from module.slack_utils import send_message_to_slack

# --- 設定 ---
GRIB2_PATH = "./data/Z__C_RJTD_20250621000000_GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin"

# --- GRIB2ファイルをxarrayで開く ---
ds = xr.open_dataset(GRIB2_PATH, engine="cfgrib", filter_by_keys={'stepType': 'instant'})
print(ds)

# 変数名の確認
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
plt.title("GSM 地上気圧 (hPa)")

IMG_PATH = "gsm_mslp_test.jpg"
plt.savefig(IMG_PATH, dpi=150)
plt.close()
print(f"[OK] 保存: {IMG_PATH}")

# --- Google Driveにアップロードし、SlackにURL通知 ---
drive_url = upload_to_drive(IMG_PATH)
send_message_to_slack(f"GSM天気図画像: {drive_url}")
print("[OK] Slack通知 完了")
