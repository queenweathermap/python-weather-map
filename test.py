# test.py
# ===============================================
# GSM/MSM 高層天気図 自動描画テスト（JMA GPV L-pall 対応）
# - 500hPa/700hPa/850hPa等の高層データを可視化
# - Google Drive連携・Slack通知・30日自動削除
# ===============================================

import os
import requests
import datetime
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import notify_slack

# === 最新のMSM L-pallファイルURL・ローカル名を生成 ===
def get_latest_gpv_file(model='MSM', level='L-pall', fh_range='FH00-15'):
    now_utc = datetime.datetime.utcnow()
    hour_cycle = (now_utc.hour // 3) * 3 - 3  # MSMは3時間おきサイクルの1つ前
    target_dt = now_utc.replace(hour=hour_cycle, minute=0, second=0, microsecond=0)
    ymd = target_dt.strftime("%Y%m%d")
    hh = target_dt.strftime("%H")
    base_url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/{target_dt.year}/{target_dt.month:02}/{target_dt.day:02}/"
    if model == 'MSM':
        fname = f"Z__C_RJTD_{ymd}{hh}0000_MSM_GPV_Rjp_{level}_{fh_range}_grib2.bin"
    elif model == 'GSM':
        fname = f"Z__C_RJTD_{ymd}{hh}0000_GSM_GPV_Rgl_L-pall_FD0000_grib2.bin"
    return base_url + fname, fname

# === GRIB2ファイルをダウンロード ===
def download_file(url, fname):
    print(f"[DL] {url}")
    res = requests.get(url)
    if res.status_code == 200:
        with open(fname, "wb") as f:
            f.write(res.content)
        print(f"[OK] Saved: {fname}")
        return True
    print(f"[NG] Download failed: {url}")
    return False

# === cfgribでxarrayデータセットとして読み込み ===
def load_gpv_grib2(file_path):
    return xr.open_dataset(file_path, engine='cfgrib')

# === 500hPa高度・渦度マップ可視化 ===
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
    print(f"[OK] Plot saved: {out_path}")

# === メイン処理 ===
def main():
    # ファイル名・日付つき生成
    now = datetime.datetime.now()
    img_name = f"msm_500hpa_{now.strftime('%Y%m%d_%H%M')}.jpg"
    img_path = os.path.join("data", img_name)
    
    # GRIB2ファイルダウンロード
    url, fname = get_latest_gpv_file('MSM', 'L-pall', 'FH00-15')
    if not download_file(url, fname):
        notify_slack("MSM L-pall高層データのダウンロードに失敗しました")
        return

    # xarrayでデータロード
    ds = load_gpv_grib2(fname)
    # 画像生成
    plot_500hpa_height_vorticity(ds, img_path)

    # 30日超のDrive画像自動削除
    delete_old_files_from_drive(
        folder_id=os.environ["DRIVE_FOLDER_ID"],
        creds_json=os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
        days=30
    )

    # Google Driveへアップロード→URL取得
    gdrive_url = upload_to_drive(img_path)

    # Slack通知
    msg = f"【自動配信】500hPa高層天気図 ({now.strftime('%Y/%m/%d %H:%M')})\n{gdrive_url}"
    notify_slack(msg)

if __name__ == "__main__":
    main()
