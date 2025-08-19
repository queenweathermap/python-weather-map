# -*- coding: utf-8 -*-
# =============================================================================
# scripts/gpv_panel_daily_akita.py
# -----------------------------------------------------------------------------
# 秋田局地 MSM パネル（エマグラム含む）自動生成 → ZIP化 → 送付
# 優先: GCS へ保存（Cloud Run 想定）。MAIL_TO があればメール送信。
# すべての書き込みは /tmp 配下（Cloud Run の書き込み可能領域）を使用。
# =============================================================================

import os
import datetime
import requests
import shutil

from module.panel_definitions import get_panel_def_akita, REGION_EXTENTS
from module.panel_utils import open_isobaric_dataset, open_surface_dataset
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.utils.mail_utils import send_mail, notify_slack
from module.utils.zip_utils import to_zip_bytes_from_dir

BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]

# Cloud Run では /tmp のみ書き込み可
DATA_DIR = "/tmp/data"
OUTPUT_DIR = "/tmp/output_akita"


def upload_to_gcs(bucket_name: str, blob_name: str, data: bytes) -> str:
    """GCS にバイナリをアップロードして gs:// パスを返す。"""
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(data)
    return f"gs://{bucket_name}/{blob_name}"


def find_latest_available_files_akita(base_url=BASE_URL, max_days=2):
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
                        file_infos.append(
                            {"url": url, "local": os.path.join(DATA_DIR, fname)}
                        )
                except Exception:
                    pass
            if len(file_infos) == 2:
                return f"{y}{m}{d}", hh, file_infos
    raise FileNotFoundError("利用可能な MSM GPV ファイルが見つかりません。")


def main():
    import inspect

    bucket  = os.environ.get("GCS_BUCKET", "").strip()
    mail_to = os.environ.get("MAIL_TO",  "").strip()

    os.makedirs(DATA_DIR,  exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    gcs_uri = None

    try:
        # 1) 最新サイクル検出
        ymd, hh, file_infos = find_latest_available_files_akita()

        # 2) ダウンロード（/tmp/data）
        for info in file_infos:
            if not os.path.exists(info["local"]):
                r = requests.get(info["url"], timeout=60)
                r.raise_for_status()
                with open(info["local"], "wb") as f:
                    f.write(r.content)
                print(f"[OK] DL: {info['local']}")

        # 3) 仕分け
        l_pall_path = next((i["local"] for i in file_infos if "L-pall" in i["local"]), None)
        lsurf_path  = next((i["local"] for i in file_infos if "Lsurf" in i["local"]), None)
        if not (l_pall_path and lsurf_path):
            raise FileNotFoundError("必要ファイル不足（L-pall/Lsurf）")

        # 4) パネル生成（署名差を吸収）
        extent = REGION_EXTENTS["akita"]
        params = set(inspect.signature(generate_universal_panel_and_notify).parameters.keys())

        def _call_plotter_with_paths():
            """msm_*_path を受け付ける実装ならそのまま使う（最優先）。"""
            if {"msm_l_pall_path", "msm_lsurf_path"} <= params:
                kwargs = {
                    "ymd": ymd, "hh": hh,
                    "output_dir": OUTPUT_DIR,
                    "drive_folder": None,
                    "city_name": "akita",
                    "extent": extent,
                    "msm_l_pall_path": l_pall_path,
                    "msm_lsurf_path":  lsurf_path,
                }
                # あれば追加、無ければ渡さない
                if "ncols" in params:  kwargs["ncols"]  = 4
                if "npages" in params: kwargs["npages"] = 4
                if "nrows" in params:  kwargs["nrows"]  = 7
                if "model" in params:  kwargs["model"]  = "MSM"

                ret = generate_universal_panel_and_notify(**kwargs)
                return ret[0] if isinstance(ret, tuple) else ret
            return None

        panel_imgs = _call_plotter_with_paths()

        if panel_imgs is None:
            # パス渡しが不可→パネル定義が必要な実装。get_panel_def_akita を安全に呼び分け
            # 必要になった時だけデータセットを開く
            ds_emagram    = open_isobaric_dataset(l_pall_path)
            ds_850        = open_isobaric_dataset(l_pall_path, hPa=850)
            ds_850_thetae = open_isobaric_dataset(l_pall_path, hPa=850)  # 必要ならθe計算に差し替え可
            ds_925        = open_isobaric_dataset(l_pall_path, hPa=925)
            ds_975        = open_isobaric_dataset(l_pall_path, hPa=975)
            ds_surface    = open_surface_dataset(lsurf_path)

            panel_def = None
            try:
                panel_def = get_panel_def_akita()  # 0引数版
            except TypeError:
                try:
                    datasets = {
                        "ds_emagram": ds_emagram,
                        "ds_850": ds_850,
                        "ds_850_thetae": ds_850_thetae,
                        "ds_925": ds_925,
                        "ds_975": ds_975,
                        "ds_surface": ds_surface,
                    }
                    panel_def = get_panel_def_akita(datasets)  # dict一個版
                except TypeError as e:
                    raise TypeError("get_panel_def_akita の呼び出しに失敗（0引数/ dict一個の両方NG）") from e

            # panel_def / panel_defs どちらを受け付けるか判定
            panel_key = "panel_def" if "panel_def" in params else ("panel_defs" if "panel_defs" in params else None)
            if panel_key is None:
                raise TypeError(f"generate_universal_panel_and_notify に 'panel_def' / 'panel_defs' がありません（params={sorted(params)}）")

            kwargs = {
                "ymd": ymd, "hh": hh,
                "output_dir": OUTPUT_DIR,
                "drive_folder": None,
                "city_name": "akita",
                "extent": extent,
                panel_key: panel_def,
            }
            if "ncols" in params:  kwargs["ncols"]  = 4
            if "npages" in params: kwargs["npages"] = 4
            if "nrows" in params:  kwargs["nrows"]  = 7
            if "model" in params:  kwargs["model"]  = "MSM"

            ret = generate_universal_panel_and_notify(**kwargs)
            panel_imgs = ret[0] if isinstance(ret, tuple) else ret

        # 5) ZIP 作成 → GCS or メール送信
        zip_bytes = to_zip_bytes_from_dir(OUTPUT_DIR)
        filename  = f"akita_panel_{ymd}_UTC{hh}.zip"
        subject   = f"秋田局地パネル {ymd} UTC{hh}"
        body      = "秋田局地（MSM）パネル出力一式です。"

        os.environ["WX_ATTACH_COUNT"] = "1"
        os.environ["WX_ERROR_COUNT"]  = "0"

        # 一時保存（Slack添付用の将来拡張に備え）
        zip_path = f"/tmp/{filename}"
        try:
            with open(zip_path, "wb") as f:
                f.write(zip_bytes)
        except Exception:
            zip_path = None

        if mail_to:
            msg_id = send_mail(
                to_addrs=mail_to,
                subject=subject,
                body=body,
                attachment_blobs=[(filename, zip_bytes, "application/zip")],
            )
            print(f"[OK] Mail sent. Message-ID: {msg_id}")
            notify_slack(
                subject=subject,
                recipients=[mail_to],
                success=True,
                files=[filename],
                upload_paths=[zip_path] if zip_path else None,
            )
        elif bucket:
            gcs_uri = upload_to_gcs(bucket, f"akita/{filename}", zip_bytes)
            print(f"[OK] Uploaded to {gcs_uri}")
            notify_slack(
                subject=subject,
                recipients=["GCS"],
                success=True,
                files=[filename],
                upload_paths=[zip_path] if zip_path else None,
            )
        else:
            # 最終退避（デバッグ用）
            fallback = f"/tmp/{filename}"
            if zip_path != fallback:
                with open(fallback, "wb") as f:
                    f.write(zip_bytes)
            print(f"[OK] Saved locally in container: {fallback}")
            notify_slack(
                subject=subject,
                recipients=["local"],
                success=True,
                files=[filename],
                upload_paths=[fallback],
            )

    except Exception as e:
        os.environ["WX_ERROR_COUNT"] = "1"
        try:
            notify_slack(
                subject=f"秋田局地パネル生成失敗 {ymd if 'ymd' in locals() else ''} UTC{hh if 'hh' in locals() else ''}",
                recipients=["system"],
                success=False,
                error=str(e),
                upload_paths=None,
            )
        finally:
            print(f"[ERROR] {e}")
            raise
    finally:
        try:
            shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
            shutil.rmtree(DATA_DIR,    ignore_errors=True)
        except Exception:
            pass



if __name__ == "__main__":
    main()
