# gsm_plot_mslp_slack.py
# =============================================
# GSM GPV GRIB2をxarrayで開いて地上気圧（msl）を日本地図上に描画し、Slackに投稿
# 必要: cfgrib, xarray, matplotlib, cartopy, slack_sdk
# =============================================

import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from slack_sdk import WebClient
import os

# --- 設定 ---
GRIB2_PATH = "./data/Z__C_RJTD_20250621000000_GSM_GPV_Rjp_Gll0p1deg_Lsurf_FD0000-0100_grib2.bin"
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")  # .envから自動読込
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID", "#weather-test")  # チャンネル名orID

# --- GRIB2ファイルをxarrayで開く ---
ds = xr.open_dataset(GRIB2_PATH, engine="cfgrib")

# 変数名の確認
print(ds.data_vars)

# "msl" = mean sea level pressure（Pa）
msl = ds["msl"].isel(time=0) / 100  # Pa→hPa
lons = ds["longitude"]
lats = ds["latitude"]

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

# --- Slackに投稿 ---
if SLACK_TOKEN:
    client = WebClient(token=SLACK_TOKEN)
    response = client.files_upload(
        channels=SLACK_CHANNEL,
        file=IMG_PATH,
        title="GSM 地上気圧天気図",
        initial_comment="GSM天気図を自動生成しました"
    )
    print(f"[SLACK] 送信結果: {response['ok']}")
else:
    print("[WARN] SLACK_BOT_TOKENが未設定なので送信スキップ")

