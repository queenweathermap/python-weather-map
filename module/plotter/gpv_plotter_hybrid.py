# module/plotter/gpv_plotter_hybrid.py
# ===============================================================
# 日本全国・ハイブリッド（GSM+MSM）天気図パネル自動生成メイン関数
# ・GSM/MSMデータ取得・読み込み
# ・8段×8列×ページ分のパネル描画
# ・jpg保存、Driveアップロード、Slack通知
# ===============================================================

import os
import datetime
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from module.core.gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS
from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_message

# 各パネルの描画関数（必要に応じて追加）
from module.plot.plot_300hpa_height_wind import plot_300hpa_height_wind
from module.plot.plot_500hpa_vorticity import plot_500hpa_vorticity
from module.plot.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

import cfgrib
import xarray as xr

DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

def generate_japan_panel_and_notify(
    ymd,
    hh,
    model="HYBRID",
    output_dir="./data",
    drive_folder=None,
    ncols=8,
    npages=2,
):
    """
    全国パネル生成＋Driveアップ＋Slack通知の一括実行関数
    """

    # --- 1. データダウンロード・読み込み ---
    dt = datetime.datetime.strptime(ymd + hh, "%Y%m%d%H")
    os.makedirs(output_dir, exist_ok=True)

    # GSM/MSMどちらも必要分DL（詳細はdownload_gpv_panelの中）
    patterns = MODEL_CONFIG["MSM"]["patterns"]  # 必要に応じてHYBRID/GSM選択可
    panel_files = download_gpv_panel(patterns, output_dir, dt, GPV_MIRROR_URLS, ncols=1)
    if not panel_files or not panel_files[0] or not all(panel_files[0]):
        raise FileNotFoundError("必要なGPVファイルが見つかりません")

    # ここではMSMの例。HYBRID時はGSM/MSM両方のファイル読み込みでOK
    l_pall_fname, _ = panel_files[0][0]
    lsurf_fname, _ = panel_files[0][1]

    # 上層・中層
    ds_isobaric = [d for d in cfgrib.open_datasets(l_pall_fname) if "isobaricInhPa" in d.variables][0]
    # 地上
    ds_surf_instant = xr.open_dataset(
        lsurf_fname, engine="cfgrib", filter_by_keys={"stepType": "instant"}
    )

    # --- 2. パネル構成定義 ---
    panel_def = [
        (plot_300hpa_height_wind, ds_isobaric, "300hPa高度・風"),
        (plot_500hpa_vorticity, ds_isobaric, "500hPa渦度"),
        (plot_700hpa_dindex_500hpa_temp, ds_isobaric, "700hPa湿数＋500hPa気温"),
        (plot_850hpa_temp_wind_700hpa_w, ds_isobaric, "850hPa温度・風＋700hPa鉛直流"),
        (plot_850hpa_thetae_stream, ds_isobaric, "850hPa θe流線"),
        (plot_975hpa_temp_wind_dindex, ds_isobaric, "975hPa温度・風・湿数"),
        (plot_925hpa_temp_wind_dindex, ds_isobaric, "925hPa温度・風・湿数"),
        (plot_surface_pressure_and_wind_msm, ds_surf_instant, "地上気圧・風・降水"),
    ]

    # --- 3. パネル描画ループ ---
    for page in range(npages):
        fig, axes = plt.subplots(
            nrows=len(panel_def), ncols=ncols,
            figsize=(ncols*3, len(panel_def)*3),
            constrained_layout=True,
            subplot_kw=dict(projection=ccrs.PlateCarree())
        )

        for row, (plot_func, ds, title) in enumerate(panel_def):
            n_steps = ds.dims["step"] if "step" in ds.dims else 1
            for col in range(ncols):
                step = page * ncols + col
                # indexエラー防止ガード
                if step >= n_steps:
                    axes[row, col].axis("off")
                    axes[row, col].set_title(f"{title} (no data)")
                    continue
                try:
                    ds_step = ds.isel(step=step)
                    plot_func(axes[row, col], ds_step)
                    axes[row, col].set_title(f"{title} (+{step*3}h)")
                except Exception as e:
                    axes[row, col].set_title(f"{title} (エラー)")
                    print(f"[ERROR] {title}: {e}")
                    axes[row, col].axis("off")

        # 全体タイトル
        page_time_range = f"{ymd} {hh}00 +{page*ncols*3}h〜+{(page+1)*ncols*3-3}h"
        fig.suptitle(f"全国天気図パネル（{page_time_range}）", fontsize=20)

        # --- 4. jpg保存 ---
        now = datetime.datetime.now()
        out_name = f"panel_japan_{ymd}{hh}_p{page+1}_{now.strftime('%Y%m%d_%H%M')}.jpg"
        out_path = os.path.join(output_dir, out_name)
        plt.savefig(out_path, dpi=300)
        plt.close()
        print("[OK] Saved:", out_path)

        # --- 5. Drive整理・アップロード ---
        if drive_folder:
            delete_old_files_from_drive(
                folder_id=DRIVE_FOLDER_ID,
                older_than_days=30,
            )
            gdrive_url = upload_to_drive(out_path, folder_id=DRIVE_FOLDER_ID)
        else:
            gdrive_url = "(未アップロード)"
            
        # --- 6. Slack通知 ---
        msg = (
            f"【自動配信】全国天気図パネル (p{page+1}/{npages}) {ymd} {hh}:00\n"
            f"{gdrive_url}"
        )
        send_slack_message(msg)

    print("[DONE] 全国天気図パネルの自動生成・通知が完了しました")
