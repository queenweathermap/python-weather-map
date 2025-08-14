# -*- coding: utf-8 -*-
# =============================================================================
# scripts/gpv_panel_daily_local.py
# -----------------------------------------------------------------------------
# 任意地点の MSM 局地パネル（7段×4列）の生成 → ZIP化 → メール添付送信
# 入力は workflow_dispatch の --lat/--lon/--label などで与える想定。
# =============================================================================

import os
import datetime
import requests
import shutil
import argparse

from module.panel_definitions import get_panel_def_local, REGION_EXTENTS
from module.panel_utils import open_isobaric_dataset, open_surface_dataset
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.utils.mail_utils import send_mail
from module.utils.zip_utils import to_zip_bytes_from_dir
from module.utils.slack_utils import send_slack_text

BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]


def find_latest_available_files_local(base_url=BASE_URL, max_days=2):
    now = datetime.datetime.utcnow()
    for day_delta in range(max_days + 1):
        day = now - datetime.timedelta(days=day_delta)
        for h in CYCLE_HOURS:
            t = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = t.strftime("%Y %m %d %H").split()
            data_url = f"{base_url}/{y}/{m}/{d}/"
            target_init = f"{y}{m}{d}{hh}0000"
            file_patterns = [
                f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
                f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin",
            ]
            infos = []
            for fname in file_patterns:
                url = f"{data_url}{fname}"
                r = requests.head(url, timeout=10)
                if r.status_code == 200:
                    infos.append({"url": url, "local": os.path.join("./data", fname)})
            if len(infos) == 2:
                return f"{y}{m}{d}", hh, infos
    raise FileNotFoundError("利用可能な MSM GPV ファイルが見つかりません。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat", type=float, required=False, help="中心緯度（任意）")
    parser.add_argument("--lon", type=float, required=False, help="中心経度（任意）")
    parser.add_argument("--label", type=str, default="local", help="地名ラベル（件名等に使用）")
    args = parser.parse_args()

    city_label = args.label or "local"
    output_dir = "./output_local"
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")

    try:
        ymd, hh, file_infos = find_latest_available_files_local()

        # DL
        os.makedirs("./data", exist_ok=True)
        for info in file_infos:
            if not os.path.exists(info["local"]):
                r = requests.get(info["url"], timeout=60)
                r.raise_for_status()
                with open(info["local"], "wb") as f:
                    f.write(r.content)
                print(f"[OK] DL: {info['local']}")

        l_pall_path = next((i["local"] for i in file_infos if "L-pall" in i["local"]), None)
        lsurf_path = next((i["local"] for i in file_infos if "Lsurf" in i["local"]), None)
        if not (l_pall_path and lsurf_path):
            raise FileNotFoundError("必要ファイル不足（L-pall/Lsurf）")

        # データセット
        ds_emagram = open_isobaric_dataset(l_pall_path)
        ds_850 = open_isobaric_dataset(l_pall_path, hPa=850)
        ds_850_thetae = open_isobaric_dataset(l_pall_path, hPa=850)
        ds_925 = open_isobaric_dataset(l_pall_path, hPa=925)
        ds_975 = open_isobaric_dataset(l_pall_path, hPa=975)
        ds_surface = open_surface_dataset(lsurf_path)

        # パネル定義（サンプル構成）
        from module.plot.plot_emagram import plot_emagram
        from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
        from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
        from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
        from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
        from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

        custom_items = [
            (plot_emagram, ds_emagram, "エマグラム"),
            (plot_850hpa_temp_wind_700hpa_w, ds_850, "850hPa気温・風・700hPa鉛直流"),
            (plot_850hpa_thetae_stream, ds_850_thetae, "850hPa相当温位・流線"),
            (plot_925hpa_temp_wind_dindex, ds_925, "925hPa気温・風・湿数"),
            (plot_975hpa_temp_wind_dindex, ds_975, "975hPa気温・風・湿数"),
            (plot_surface_pressure_and_wind_msm, ds_surface, "地上"),
            (None, None, ""),  # 余白
        ]
        panel_def_local = get_panel_def_local(custom_items, total_rows=7)

        # 地域範囲（指定なければデフォルト）
        extent = REGION_EXTENTS.get(city_label, REGION_EXTENTS["japan"])

        # 生成
        os.makedirs(output_dir, exist_ok=True)
        panel_imgs, _, _ = generate_universal_panel_and_notify(
            ymd=ymd,
            hh=hh,
            model="MSM",
            output_dir=output_dir,
            drive_folder=None,
            ncols=4,
            npages=4,
            panel_def=panel_def_local,
            nrows=7,
            city_name=city_label,
            extent=extent,
        )

        # メール
        zip_bytes = to_zip_bytes_from_dir(output_dir)
        subject = f"{city_label} 局地パネル {ymd} UTC{hh}"
        body = f"{city_label} の MSM 局地パネル出力一式をZIP添付します（保存なし運用）。"

        msg_id = send_mail(
            to_addrs=os.environ.get("MAIL_TO", ""),
            subject=subject,
            body=body,
            attachment_blobs=[(f"{city_label}_panel_{ymd}_UTC{hh}.zip", zip_bytes, "application/zip")],
        )
        print(f"[OK] Mail sent. Message-ID: {msg_id}")

        if slack_channel:
            try:
                fnames = ", ".join(sorted(os.listdir(output_dir)))
                send_slack_text(
                    channel=slack_channel,
                    message=f"🟡 任意局地パネル送信 {ymd} UTC{hh} ({city_label})\nMessage-ID: {msg_id}\nfiles: {fnames}",
                )
            except Exception:
                pass

    except Exception as e:
        if slack_channel:
            send_slack_text(channel=slack_channel, message=f":x: 任意局地パネル失敗: {e}")
        print(f"[ERROR] {e}")
        raise
    finally:
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
