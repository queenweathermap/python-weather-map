# -*- coding: utf-8 -*-
# =============================================================================
# scripts/gpv_panel_daily_akita.py
# -----------------------------------------------------------------------------
# 秋田局地 MSM パネル（エマグラム含む）自動生成 → ZIP化 → メール添付送信
# ※ Drive 不使用／保存しない運用
# =============================================================================

import os
import datetime
import requests
import shutil

from module.panel_definitions import get_panel_def_akita, REGION_EXTENTS
from module.panel_utils import open_isobaric_dataset, open_surface_dataset
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify  # 画像生成に利用（Drive機能は使わない）
from module.utils.mail_utils import send_mail
from module.utils.zip_utils import to_zip_bytes_from_dir
from module.utils.slack_utils import send_slack_text

BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]


def find_latest_available_files_akita(base_url=BASE_URL, max_days=2):
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
            file_infos = []
            for fname in file_patterns:
                url = f"{data_url}{fname}"
                r = requests.head(url, timeout=10)
                if r.status_code == 200:
                    file_infos.append({"url": url, "local": os.path.join("./data", fname)})
            if len(file_infos) == 2:
                return f"{y}{m}{d}", hh, file_infos
    raise FileNotFoundError("利用可能な MSM GPV ファイルが見つかりません。")


def main():
    slack_channel = os.environ.get("SLACK_CHANNEL_ID")
    output_dir = "./output_akita"

    try:
        # 1) ソース取得
        ymd, hh, file_infos = find_latest_available_files_akita()

        # 2) ダウンロード
        os.makedirs("./data", exist_ok=True)
        for info in file_infos:
            if not os.path.exists(info["local"]):
                r = requests.get(info["url"], timeout=60)
                r.raise_for_status()
                with open(info["local"], "wb") as f:
                    f.write(r.content)
                print(f"[OK] DL: {info['local']}")

        # 3) 仕分け
        l_pall_path = next((i["local"] for i in file_infos if "L-pall" in i["local"]), None)
        lsurf_path = next((i["local"] for i in file_infos if "Lsurf" in i["local"]), None)
        if not (l_pall_path and lsurf_path):
            raise FileNotFoundError("必要ファイル不足（L-pall/Lsurf）")

        # 4) データセット抽出
        ds_emagram = open_isobaric_dataset(l_pall_path)
        ds_850 = open_isobaric_dataset(l_pall_path, hPa=850)
        ds_850_thetae = open_isobaric_dataset(l_pall_path, hPa=850)  # 必要ならθe計算に差し替え
        ds_925 = open_isobaric_dataset(l_pall_path, hPa=925)
        ds_975 = open_isobaric_dataset(l_pall_path, hPa=975)
        ds_surface = open_surface_dataset(lsurf_path)

        panel_def = get_panel_def_akita(ds_emagram, ds_850, ds_850_thetae, ds_925, ds_975, ds_surface)
        extent = REGION_EXTENTS["akita"]

        # 5) パネル生成（Drive機能は使わず、出力だけ生成）
        os.makedirs(output_dir, exist_ok=True)
        # generate_universal_panel_and_notify は Drive/Slack を返す仕様のため、
        # ここでは出力（panel_imgs, zip_path, drive_url）のうち panel_imgs だけ使う想定。
        panel_imgs, _, _ = generate_universal_panel_and_notify(
            ymd=ymd,
            hh=hh,
            model="MSM",
            output_dir=output_dir,
            drive_folder=None,  # 無効
            ncols=4,
            npages=4,
            panel_def=panel_def,
            nrows=7,
            city_name="akita",
            extent=extent,
        )

        # 6) メール送信（ZIPはメモリ上）
        zip_bytes = to_zip_bytes_from_dir(output_dir)
        subject = f"秋田局地パネル {ymd} UTC{hh}"
        body = "秋田局地（MSM）パネル出力一式をZIP添付します（保存なし運用）。"

        msg_id = send_mail(
            to_addrs=os.environ.get("MAIL_TO", ""),
            subject=subject,
            body=body,
            attachment_blobs=[(f"akita_panel_{ymd}_UTC{hh}.zip", zip_bytes, "application/zip")],
        )
        print(f"[OK] Mail sent. Message-ID: {msg_id}")

        if slack_channel:
            try:
                fnames = ", ".join(sorted(os.listdir(output_dir)))
                send_slack_text(
                    channel=slack_channel,
                    message=f":red_circle: 秋田パネル送信 {ymd} UTC{hh}\nMessage-ID: {msg_id}\nfiles: {fnames}",
                )
            except Exception:
                pass

    except Exception as e:
        if slack_channel:
            send_slack_text(channel=slack_channel, message=f":x: 秋田パネル失敗: {e}")
        print(f"[ERROR] {e}")
        raise
    finally:
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
