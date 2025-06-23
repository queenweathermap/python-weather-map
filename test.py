# test.py
# ===============================================
# GSM/MSM 高層天気図 自動描画テスト（JMA GPV L-pall 対応）
# - 500hPa/700hPa/850hPa等の高層データを可視化
# - Google Drive連携・Slack通知
# ===============================================

import os
import datetime
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from module.utils.drive_utils import upload_to_drive
from module.utils.slack_utils import notify_slack

# --- 最新のMSM/GSM L-pallファイル名を組み立てる ---
def get_latest_gpv_file(model='MSM', level='L-pall', fh_range='FH00-15'):
    now_utc = datetime.datetime.utcnow()
    hour_cycle = (now_utc.hour // 3) * 3 - 3  # MSM用(安全に3h前)
    target_dt = now_utc.replace(hour=hour_cycle, minute=0, second=0, microsecond=0)
    ymd = target_dt.strftime("%Y%m%d")
    hh = target_dt.strftime("%H")
    base_url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/{target_dt.year}/{target_dt.month:02}/{target_dt.day:02}/"
    if model == 'MSM':
        fname = f"Z__C_RJTD_{ymd}{hh}0000_MSM_GPV_Rjp_{level}_{fh_range}_grib2.bin"
    elif model == 'GSM':
        # 例: FD0000～FD0036 のループで取得
        fname = f"Z__C_RJTD_{ymd}{hh}0000_GSM_GPV_Rgl_L-pall_FD0000_grib2.bin"
    return base_url + fname, fname

# --- GRIB2ファイルをダウンロード（省略、requestsでOK） ---

# --- cfgribでxarrayデータセットとして読み込み ---
def load_gpv_grib2(file_path):
    return xr.open_dataset(file_path, engine='cfgrib')

# --- 可視化例: 500hPa高度＆渦度 ---
def plot_500hpa_height_vorticity(ds, out_path):
    hgt = ds['gh'].sel(isobaricInhPa=500) / 10  # (gpdm)
    try:
        vort = ds['vo'].sel(isobaricInhPa=500) * 1e5  # (1e-5/s)
    except KeyError:
        vort = None
    lons = ds['longitude'].values
    lats = ds['latitude'].values

    proj = ccrs.PlateCarree()
    fig, ax = plt.subplots(figsize=(8,8), subplot_kw={'projection': proj})
    ax.set_extent([120, 150, 22, 48], crs=proj)
    ax.coastlines()
    cs = ax.contour(lons, lats, hgt, levels=range(500, 600, 6), colors='black')
    ax.clabel(cs, fmt='%d', fontsize=8)
    if vort is not None:
        vplot = ax.contourf(lons, lats, vort, levels=range(-30, 40, 5), cmap='RdBu', alpha=0.6)
        fig.colorbar(vplot, ax=ax, label="Vorticity ($10^{-5}$/s)")
    plt.title("500hPa Height/Vorticity")
    plt.savefig(out_path, dpi=150)
    plt.close()

# --- Google Driveアップロード＆Slack通知 ---
def main():
    url, fname = get_latest_gpv_file('MSM', 'L-pall', 'FH00-15')
    # (1) ダウンロード (省略)
    # (2) xarrayで読込
    ds = load_gpv_grib2(fname)
    # (3) 高層天気図を描画
    out_path = 'panel_500hpa_vort.jpg'
    plot_500hpa_height_vorticity(ds, out_path)
    # (4) Driveアップ・Slack通知
    gdrive_url = upload_to_drive(out_path)
    notify_slack(f"500hPa天気図: {gdrive_url}")

if __name__ == "__main__":
    main()
