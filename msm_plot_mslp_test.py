# msm_prmsl_dl_plot.py
# ===============================
# MSM地上気圧をDL・描画・Driveアップ・Slack通知
# ===============================

import os
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from datetime import datetime
from module.utils.drive_utils import upload_to_drive
from module.utils.slack_utils import send_slack_text

BASE_DIR = "./data"
os.makedirs(BASE_DIR, exist_ok=True)

# 対象ファイル名（自動取得も可）
init_dt = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
ymd = init_dt.strftime("%Y%m%d")
h = init_dt.strftime("%H")
fname = f"Z__C_RJTD_{ymd}{h}0000_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin"
grib2_path = os.path.join(BASE_DIR, fname)

# --- DLなければDL ---
if not os.path.exists(grib2_path) or os.path.getsize(grib2_path) < 10_000_000:
    url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/{init_dt.year}/{init_dt.strftime('%m')}/{init_dt.strftime('%d')}/{fname}"
    print(f"[DL] {url}")
    import urllib.request
    urllib.request.urlretrieve(url, grib2_path)
    print(f"[OK] DL: {grib2_path}")

# --- データ読込 ---
ds = xr.open_dataset(grib2_path, engine="cfgrib", filter_by_keys={'stepType': 'instant'})

print(ds)
print("[VAR]", list(ds.data_vars))

# --- 描画 ---
msl = ds["prmsl"].isel(step=0) / 100  # Pa→hPa
lons = ds["longitude"]
lats = ds["latitude"]

fig = plt.figure(figsize=(9, 7))
ax = plt.axes(projection=ccrs.PlateCarree())
ax.set_extent([120, 150, 22, 48], crs=ccrs.PlateCarree())
ax.coastlines(resolution="50m")
cs = ax.contour(lons, lats, msl, levels=range(960, 1050, 4), colors='black')
ax.clabel(cs, fmt="%.0f", fontsize=8)
plt.title("MSM 地上気圧 (hPa)")

save_path = os.path.join(BASE_DIR, "msm_prmsl_test.jpg")
plt.savefig(save_path, bbox_inches="tight", dpi=150)
plt.close()
print("[OK] 保存:", save_path)

# --- Google Drive & Slack ---
drive_url = upload_to_drive(save_path)
print("[OK] Drive:", drive_url)

send_slack_text(
    channel=os.environ["SLACK_CHANNEL_ID"],
    message=f"MSM地上気圧天気図を自動生成・アップロードしました\n{drive_url}"
)
print("[OK] Slack通知 完了")
