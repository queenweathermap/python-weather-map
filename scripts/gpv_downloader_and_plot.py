# scripts/gpv_downloader_and_plot.py
# ===============================================
# JMA GPV GSM/MSM データ自動ダウンロード＆GRIB2直読み＆天気図描画
# NetCDF変換は不要・cfgribで直接可視化
# 2025-06-27 by ChatGPT 新core設計準拠
# ===============================================

import os
from module.core.gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS
from module.core.gpv_data_loader import load_grib2
from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

import matplotlib.pyplot as plt
import cartopy.crs as ccrs

# 日本語フォント（IPAGothic）を指定
plt.rcParams['font.family'] = 'IPAGothic'

def main(yyyymmddhh, model="GSM", out_dir="./data"):
    # ダウンロード
    patterns = MODEL_CONFIG[model]["patterns"]
    dt = pd.to_datetime(yyyymmddhh, format="%Y%m%d%H")
    files = download_gpv_panel(patterns, out_dir, dt, GPV_MIRROR_URLS, ncols=1)
    if not files or not files[0] or not all(files[0]):
        print("[ERROR] GPVファイルが見つかりません")
        return

    grib_path, _ = files[0][0]
    ds = load_grib2(grib_path)
    if ds is None:
        print("[ERROR] GRIB2読込失敗")
        return

    # 描画（例：地上天気図）
    fig, ax = plt.subplots(subplot_kw=dict(projection=ccrs.PlateCarree()))
    plot_surface_pressure_and_wind_msm(ax, ds, step=0)
    plt.savefig(os.path.join(out_dir, f"{model}_surface_{yyyymmddhh}.jpg"), dpi=150)
    plt.close()
    print(f"[OK] Saved: {os.path.join(out_dir, f'{model}_surface_{yyyymmddhh}.jpg')}")

if __name__ == "__main__":
    main("2024062000", model="GSM")
