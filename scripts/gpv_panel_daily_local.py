# -*- coding: utf-8 -*-
# =============================================================================
# scripts/gpv_panel_daily_local.py
# -----------------------------------------------------------------------------
# 任意領域（緯度経度BBox）で MSM パネルを自動生成 → 送付
# - Cloud Run Jobs / ローカルのどちらでも動作
# - 画像複数添付（MAIL_ATTACH_IMAGES=1）または ZIP 添付
# - GCS_BUCKET があれば ZIP を GCS に保存可能
# =============================================================================

import os
import datetime
import requests
import shutil
import traceback

from module.panel_definitions import get_panel_def_local, REGION_EXTENTS
from module.panel_utils import open_isobaric_dataset, open_surface_dataset
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.utils.mail_utils import send_mail, notify_slack
from module.utils.zip_utils import to_zip_bytes_from_dir

# --- 取得元（京都大学RISHのアーカイブ） ---
BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]

# Cloud Run では /tmp のみ書き込み可
DATA_DIR = "/tmp/data"
OUTPUT_DIR = "/tmp/output_local"


def upload_to_gcs(bucket_name: str, blob_name: str, data: bytes) -> str:
    """GCS にバイナリをアップロードして gs:// パスを返す。"""
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(data)
    return f"gs://{bucket_name}/{blob_name}"


def find_latest_available_files(base_url=BASE_URL, max_days=2):
    """直近で取得可能な MSM GPV(Rjp L-pall/Lsurf) を探す。"""
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
                try:
                    r = requests.head(url, timeout=10)
                    if r.status_code == 200:
                        file_infos.append({"url": url, "local": os.path.join(DATA_DIR, fname)})
                except Exception:
                    pass
            if len(file_infos) == 2:
                return f"{y}{m}{d}", hh, file_infos
    raise FileNotFoundError("利用可能な MSM GPV ファイルが見つかりません。")


def parse_bbox(env_value: str):
    """'minlon,maxlon,minlat,maxlat' を [minlon,maxlon,minlat,maxlat] に"""
    try:
        parts = [float(x.strip()) for x in env_value.split(",")]
        if len(parts) == 4:
            return parts
    except Exception:
        pass
    return None


def build_local_panel_def(var_dict):
    """
    任意地パネルのレイアウト（8段上限のうち6段使用）。
    get_panel_def_local([(plot_func, ds_dict, title), ...]) を利用。
    """
    from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
    from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
    from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
    from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
    from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

    items = [
        # 1: 850hPa温度・風＋700hPa鉛直流
        (plot_850hpa_temp_wind_700hpa_w, {
            "t_850": var_dict.get("t_850"),
            "u_850": var_dict.get("u_850"),
            "v_850": var_dict.get("v_850"),
            "w_700": var_dict.get("w_700"),
        }, "850hPa温度・風 + 700hPa鉛直流"),

        # 2: 850hPa θe 流線
        (plot_850hpa_thetae_stream, {
            "t_850": var_dict.get("t_850"),
            "r_850": var_dict.get("r_850"),
            "u_850": var_dict.get("u_850"),
            "v_850": var_dict.get("v_850"),
        }, "850hPa 相当温位・流線"),

        # 3: 925hPa 気温・風・湿数
        (plot_925hpa_temp_wind_dindex, {
            "t_925": var_dict.get("t_925"),
            "u_925": var_dict.get("u_925"),
            "v_925": var_dict.get("v_925"),
            "r_925": var_dict.get("r_925"),
        }, "925hPa 気温・風・湿数"),

        # 4: 975hPa 気温・風・湿数
        (plot_975hpa_temp_wind_dindex, {
            "t_975": var_dict.get("t_975"),
            "u_975": var_dict.get("u_975"),
            "v_975": var_dict.get("v_975"),
            "r_975": var_dict.get("r_975"),
        }, "975hPa 気温・風・湿数"),

        # 5: 地上（海面更正気圧・10m風・降水）
        (plot_surface_pressure_wind_precip, {
            "prmsl": var_dict.get("prmsl"),
            "u10":   var_dict.get("u10"),
            "v10":   var_dict.get("v10"),
            # "apcp":  var_dict.get("apcp"),  # 降水を使う場合は plot 側の引数と合わせて有効化
        }, "地上 気圧・風（降水）"),

        # 6: 予備（空欄）
        (None, None, ""),
    ]

    return get_panel_def_local(items, total_rows=8)  # 上限8段のテンプレに合わせてパディング


def main():
    bucket  = os.environ.get("GCS_BUCKET", "").strip()
    mail_to = os.environ.get("MAIL_TO", "").strip()
    attach_images = os.environ.get("MAIL_ATTACH_IMAGES", "0") == "1"

    local_name = os.environ.get("LOCAL_NAME", "local").strip() or "local"
    bbox_env   = os.environ.get("LOCAL_BBOX", "").strip()
    extent     = parse_bbox(bbox_env) or REGION_EXTENTS.get("japan")

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ymd = hh = None
    try:
        # 1) ソース探索
        ymd, hh, file_infos = find_latest_available_files()

        # 2) ダウンロード
        for info in file_infos:
            if not os.path.exists(info["local"]):
                r = requests.get(info["url"], timeout=60)
                r.raise_for_status()
                with open(info["local"], "wb") as f:
                    f.write(r.content)
                print(f"[OK] DL: {info['local']}")

        # 3) 必要ファイルの仕分け
        l_pall_path = next((i["local"] for i in file_infos if "L-pall" in i["local"]), None)
        lsurf_path  = next((i["local"] for i in file_infos if "Lsurf" in i["local"]), None)
        if not (l_pall_path and lsurf_path):
            raise FileNotFoundError("必要ファイル不足（L-pall / Lsurf）")

        # 4) データセット抽出（任意地パネルで使う層）
        ds_850 = open_isobaric_dataset(l_pall_path, hPa=850)
        ds_925 = open_isobaric_dataset(l_pall_path, hPa=925)
        ds_975 = open_isobaric_dataset(l_pall_path, hPa=975)
        ds_700 = open_isobaric_dataset(l_pall_path, hPa=700)   # 鉛直流 w 用
        ds_sfc = open_surface_dataset(lsurf_path)

        # 5) var_dict（ユニバーサル描画に渡すキーを統一）
        var_dict = {
            # 850
            "t_850": ds_850.get("t") if hasattr(ds_850, "get") else ds_850["t"] if "t" in ds_850 else ds_850,
            "u_850": ds_850.get("u") if hasattr(ds_850, "get") else ds_850["u"] if "u" in ds_850 else None,
            "v_850": ds_850.get("v") if hasattr(ds_850, "get") else ds_850["v"] if "v" in ds_850 else None,
            "r_850": ds_850.get("r") if hasattr(ds_850, "get") else ds_850["r"] if "r" in ds_850 else None,
            # 925
            "t_925": ds_925.get("t") if hasattr(ds_925, "get") else ds_925["t"] if "t" in ds_925 else ds_925,
            "u_925": ds_925.get("u") if hasattr(ds_925, "get") else ds_925["u"] if "u" in ds_925 else None,
            "v_925": ds_925.get("v") if hasattr(ds_925, "get") else ds_925["v"] if "v" in ds_925 else None,
            "r_925": ds_925.get("r") if hasattr(ds_925, "get") else ds_925["r"] if "r" in ds_925 else None,
            # 975
            "t_975": ds_975.get("t") if hasattr(ds_975, "get") else ds_975["t"] if "t" in ds_975 else ds_975,
            "u_975": ds_975.get("u") if hasattr(ds_975, "get") else ds_975["u"] if "u" in ds_975 else None,
            "v_975": ds_975.get("v") if hasattr(ds_975, "get") else ds_975["v"] if "v" in ds_975 else None,
            "r_975": ds_975.get("r") if hasattr(ds_975, "get") else ds_975["r"] if "r" in ds_975 else None,
            # 700 w
            "w_700": ds_700.get("w") if hasattr(ds_700, "get") else ds_700["w"] if "w" in ds_700 else None,
            # 地上
            "prmsl": ds_sfc.get("prmsl") if hasattr(ds_sfc, "get") else ds_sfc["prmsl"] if "prmsl" in ds_sfc else None,
            "u10":   ds_sfc.get("u10")  if hasattr(ds_sfc, "get") else ds_sfc["u10"]  if "u10"  in ds_sfc else None,
            "v10":   ds_sfc.get("v10")  if hasattr(ds_sfc, "get") else ds_sfc["v10"]  if "v10"  in ds_sfc else None,
            # "apcp":  ...  # 必要になれば加える（累積→差分生成はユニバーサル側に実装済み）
        }

        panel_def = build_local_panel_def(var_dict)

        # 6) パネル生成（prebuilt_var_dict / panel_def_override を渡す）
        panel_imgs, _, _ = generate_universal_panel_and_notify(
            ymd=ymd,
            hh=hh,
            output_dir=OUTPUT_DIR,
            drive_folder=None,
            ncols=4,
            npages=4,
            city_name=local_name,
            extent=extent,
            prebuilt_var_dict=var_dict,
            panel_def_override=panel_def,
        )

        # 7) 送付
        subject = f"[Python天気図] 任意地パネル {local_name} {ymd} UTC{hh}"
        body    = f"{local_name} のMSMパネル出力一式です。"
        os.environ["WX_ERROR_COUNT"] = "0"

        if attach_images:
            attachments = []
            for p in sorted(panel_imgs):
                with open(p, "rb") as f:
                    attachments.append((os.path.basename(p), f.read(), "image/jpeg"))
            os.environ["WX_ATTACH_COUNT"] = str(len(attachments))

            if mail_to:
                msg_id = send_mail(
                    to_addrs=mail_to, subject=subject, body=body, attachment_blobs=attachments
                )
                print(f"[OK] Mail sent. Message-ID: {msg_id}")
                notify_slack(
                    subject=subject, recipients=[mail_to], success=True,
                    files=[a[0] for a in attachments], upload_paths=None
                )
            elif bucket:
                zip_bytes = to_zip_bytes_from_dir(OUTPUT_DIR)
                gcs_uri = upload_to_gcs(bucket, f"{local_name}/{local_name}_panel_{ymd}_UTC{hh}.zip", zip_bytes)
                print(f"[OK] Uploaded to {gcs_uri}")
                os.environ["WX_ATTACH_COUNT"] = "1"
                notify_slack(
                    subject=subject, recipients=["GCS"], success=True,
                    files=[f"{local_name}_panel_{ymd}_UTC{hh}.zip"], upload_paths=None
                )
            else:
                print("[OK] No MAIL_TO/GCS_BUCKET. Skipped delivery.")
        else:
            zip_bytes = to_zip_bytes_from_dir(OUTPUT_DIR)
            zip_name  = f"{local_name}_panel_{ymd}_UTC{hh}.zip"
            os.environ["WX_ATTACH_COUNT"] = "1"

            if mail_to:
                msg_id = send_mail(
                    to_addrs=mail_to, subject=subject, body=body,
                    attachment_blobs=[(zip_name, zip_bytes, "application/zip")]
                )
                print(f"[OK] Mail sent. Message-ID: {msg_id}")
                notify_slack(
                    subject=subject, recipients=[mail_to], success=True,
                    files=[zip_name], upload_paths=None
                )
            elif bucket:
                gcs_uri = upload_to_gcs(bucket, f"{local_name}/{zip_name}", zip_bytes)
                print(f"[OK] Uploaded to {gcs_uri}")
                notify_slack(
                    subject=subject, recipients=["GCS"], success=True,
                    files=[zip_name], upload_paths=None
                )
            else:
                with open(f"/tmp/{zip_name}", "wb") as f:
                    f.write(zip_bytes)
                print(f"[OK] Saved locally: /tmp/{zip_name}")
                notify_slack(
                    subject=subject, recipients=["local"], success=True,
                    files=[zip_name], upload_paths=[f"/tmp/{zip_name}"],
                )

    except Exception as e:
        os.environ["WX_ERROR_COUNT"] = "1"
        traceback.print_exc()
        try:
            notify_slack(
                subject=f"任意地パネル生成失敗 {local_name} {ymd or ''} UTC{hh or ''}",
                recipients=["system"],
                success=False,
                error=str(e),
                upload_paths=None,
            )
        finally:
            print(f"[ERROR] {e}", flush=True)
        raise
    finally:
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR,    ignore_errors=True)


if __name__ == "__main__":
    main()
