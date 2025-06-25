# gpv_panel_daily_japan_msm.py
# ===============================================================
# MSMパネル自動生成スクリプト（GRIB2ダウンロード・cfgrib対応・Drive保存・Slack通知・クリーンアップ付き）
# 2025-06-23 ChatGPT改訂・デバッグ用print追加
# ===============================================================

import os
import datetime
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs   # ← これ重要！
import cfgrib

from gpv_downloader import download_gpv_panel, MODEL_CONFIG, GPV_MIRROR_URLS

from module.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
from module.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

from module.utils.drive_utils import upload_to_drive, delete_old_files_from_drive
from module.utils.slack_utils import send_slack_message

from module.utils.var_utils import get_var_2d


def main():
    ymd = '20240622'
    hh = '12'
    dt = datetime.datetime.strptime(ymd + hh, "%Y%m%d%H")
    base_dir = "./data"
    os.makedirs(base_dir, exist_ok=True)

    patterns = MODEL_CONFIG["MSM"]["patterns"]
    panel_files = download_gpv_panel(patterns, base_dir, dt, GPV_MIRROR_URLS, ncols=1)
    if not panel_files or not panel_files[0] or not all(panel_files[0]):
        raise FileNotFoundError("必要なMSMファイルが見つかりません")

    l_pall_fname, _ = panel_files[0][0]
    lsurf_fname, _ = panel_files[0][1]

    # -- 必要なレベルだけfilterで読む！ --
    ds_list = cfgrib.open_datasets(l_pall_fname)
    ds = [d for d in ds_list if "isobaricInhPa" in d.variables][0]

    # --- ここで変数取得OK ---
    temp_850 = get_var_2d(ds, "TMP_850mb", time_idx=0)    # 850hPa温度 2D
    rh_700   = get_var_2d(ds, "RH_700mb",  time_idx=0)    # 700hPa相対湿度 2D

    print("temp_850 shape:", temp_850.shape if temp_850 is not None else None)
    print("rh_700 shape:", rh_700.shape if rh_700 is not None else None)

    print("==== isobaricInhPa levels ====")
    print(ds.coords["isobaricInhPa"].values)
    
    for level in [850, 700, 500]:
        arr = get_var_2d(ds, "TMP_{}mb".format(level), level=level)
        print(f"T at {level}hPa:", None if arr is None else arr.shape)

    
    # 地表・積算は従来どおり
    ds_surf_instant = xr.open_dataset(
        lsurf_fname, engine="cfgrib",
        filter_by_keys={"stepType": "instant"}
    )
    ds_surf_accum = xr.open_dataset(
        lsurf_fname, engine="cfgrib",
        filter_by_keys={"stepType": "accum"}
    )

    # --- 必要な変数が取れるかデバッグ用print
    print("==== DEBUG: ds.variables ====")
    print(list(ds.variables))
    print("==== DEBUG: ds_surf_instant.variables ====")
    print(list(ds_surf_instant.variables))
    print("==== DEBUG: ds_surf_accum.variables ====")
    print(list(ds_surf_accum.variables))

    # --- パネル作成 ---
    fig, axes = plt.subplots(
        nrows=6, ncols=1, figsize=(8, 48),
        constrained_layout=True,
        subplot_kw=dict(projection=ccrs.PlateCarree())
    )
    fig.suptitle(f"MSM日本全域 天気図6種 {ymd} {hh}00", fontsize=22)
    
    plot_700hpa_dindex_500hpa_temp(axes[0], ds)
    axes[0].set_title("700hPa D-index / 500hPa 気温")
    
    plot_850hpa_temp_wind_700hpa_w(axes[1], ds)
    axes[1].set_title("850hPa気温・風 + 700hPa鉛直流")
    
    plot_850hpa_thetae_stream(axes[2], ds)
    axes[2].set_title("850hPa θe + Stream")
    
    plot_975hpa_temp_wind_dindex(axes[3], ds)
    axes[3].set_title("975hPa気温・風・D-index")
    
    plot_925hpa_temp_wind_dindex(axes[4], ds)
    axes[4].set_title("925hPa気温・風・D-index")
    
    plot_surface_pressure_and_wind_msm(axes[5], ds_surf_instant)
    axes[5].set_title("地上: 等圧線・風・降水")

    # --- 各段で変数存在チェックprint（省略せず推奨）---
    try:
        print("[パネル1] plot_700hpa_dindex_500hpa_temp 実行")
        plot_700hpa_dindex_500hpa_temp(axes[0], ds)
        axes[0].set_title("700hPa D-index / 500hPa 気温")
    except Exception as e:
        print("[ERROR] plot_700hpa_dindex_500hpa_temp:", e)

    try:
        print("[パネル2] plot_850hpa_temp_wind_700hpa_w 実行")
        plot_850hpa_temp_wind_700hpa_w(axes[1], ds)
        axes[1].set_title("850hPa気温・風 + 700hPa鉛直流")
    except Exception as e:
        print("[ERROR] plot_850hpa_temp_wind_700hpa_w:", e)

    try:
        print("[パネル3] plot_850hpa_thetae_stream 実行")
        plot_850hpa_thetae_stream(axes[2], ds)
        axes[2].set_title("850hPa θe + Stream")
    except Exception as e:
        print("[ERROR] plot_850hpa_thetae_stream:", e)

    try:
        print("[パネル4] plot_975hpa_temp_wind_dindex 実行")
        plot_975hpa_temp_wind_dindex(axes[3], ds)
        axes[3].set_title("975hPa気温・風・D-index")
    except Exception as e:
        print("[ERROR] plot_975hpa_temp_wind_dindex:", e)

    try:
        print("[パネル5] plot_925hpa_temp_wind_dindex 実行")
        plot_925hpa_temp_wind_dindex(axes[4], ds)
        axes[4].set_title("925hPa気温・風・D-index")
    except Exception as e:
        print("[ERROR] plot_925hpa_temp_wind_dindex:", e)

    try:
        print("[パネル6] plot_surface_pressure_and_wind_msm 実行")
        plot_surface_pressure_and_wind_msm(axes[5], ds_surf_instant)
        axes[5].set_title("地上: 等圧線・風・降水")
    except Exception as e:
        print("[ERROR] plot_surface_pressure_and_wind_msm:", e)

    # --- 保存・Driveアップロード・Slack通知 ---
    now = datetime.datetime.now()
    out_path = os.path.join(base_dir, f"msm_panel_{ymd}{hh}_{now.strftime('%Y%m%d_%H%M')}.jpg")
    plt.savefig(out_path, dpi=150)
    plt.close()
    print("[OK] Saved:", out_path)

    delete_old_files_from_drive(
        folder_id=os.environ["DRIVE_FOLDER_ID"],
        creds_json=os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
        days=30
    )
    gdrive_url = upload_to_drive(out_path)
    msg = f"【自動配信】MSM全国天気図6種パネル ({ymd} {hh}:00)\n{gdrive_url}"
    send_slack_message(msg)

if __name__ == "__main__":
    main()
