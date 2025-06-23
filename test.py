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
import numpy as np

from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_message

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

def open_grib_select_var(fname, var_name, level):
    ds = xr.open_dataset(
        fname,
        engine='cfgrib',
        filter_by_keys={'typeOfLevel': 'isobaricInhPa', 'shortName': var_name, 'level': level}
    )
    arr = ds[var_name]
    # 2Dになるまで次元を落とす
    while arr.ndim > 2:
        arr = arr.isel({arr.dims[0]: 0})
    arr = arr.squeeze()
    print(var_name, "shape after squeeze:", arr.shape)
    return arr

# === 500hPa高度・渦度マップ可視化 ===
def plot_500hpa_height_vorticity_grib(fname, out_path):
    hgt = open_grib_select_var(fname, 'gh', 500) / 10
    try:
        vort = open_grib_select_var(fname, 'vo', 500) * 1e5
    except Exception:
        vort = None
    print("hgt shape:", hgt.shape)
    lats = hgt.latitude.values
    lons = hgt.longitude.values

    proj = ccrs.PlateCarree()
    fig, ax = plt.subplots(figsize=(8,8), subplot_kw={'projection': proj})
    ax.set_extent([120, 150, 22, 48], crs=proj)
    ax.coastlines()
    cs = ax.contour(lons, lats, hgt, levels=np.arange(500, 600, 6), colors='black')
    ax.clabel(cs, fmt='%d', fontsize=8)
    if vort is not None:
        vplot = ax.contourf(lons, lats, vort, levels=np.arange(-30, 40, 5), cmap='RdBu', alpha=0.6)
        fig.colorbar(vplot, ax=ax, label="Vorticity ($10^{-5}$/s)")
    plt.title("500hPa Height/Vorticity")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[OK] Plot saved: {out_path}")

# === メイン処理（テスト用：日付・時刻をハードコーディング）===
def main():
    # 必ず存在する過去データでハードコーディング例
    ymd = '20240622'    # ← ここは必ずRISHに実在する日付に合わせて変更
    hh = '12'           # ← 00,03,06,09,12,15,18,21 のどれか
    fname = f"Z__C_RJTD_{ymd}{hh}0000_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin"
    base_url = f"https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original/2024/06/22/"
    url = base_url + fname
    print("[DL]", url)

    now = datetime.datetime.now()
    img_name = f"msm_500hpa_{now.strftime('%Y%m%d_%H%M')}.jpg"
    img_dir = "data"
    img_path = os.path.join(img_dir, img_name)

    # 保存先ディレクトリを必ず作成
    os.makedirs(img_dir, exist_ok=True)

    # GRIB2ファイルダウンロード
    if not download_file(url, fname):
        send_slack_message("ダウンロード失敗")
        return

    # 500hPa天気図を描画
    plot_500hpa_height_vorticity_grib(fname, img_path)

    # Google Driveの30日自動削除
    delete_old_files_from_drive(
        folder_id=os.environ["DRIVE_FOLDER_ID"],
        creds_json=os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
        days=30
    )

    # Google Driveにアップロードし、Slack通知
    gdrive_url = upload_to_drive(img_path)
    msg = f"【自動配信】500hPa高層天気図 ({now.strftime('%Y/%m/%d %H:%M')})\n{gdrive_url}"
    send_slack_message(msg)

if __name__ == "__main__":
    main()
