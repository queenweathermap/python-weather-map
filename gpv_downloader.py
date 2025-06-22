# gpv_downloader.py
# ===============================================================
# GPVファイルのダウンロード・自動パネル描画ユーティリティ
# MSM/GSM/ローカルもモデル名で一括運用（パターン自動分岐）
# 2025-06-22 by ChatGPT
# ===============================================================

import os
import urllib.request
from datetime import datetime, timedelta
import pandas as pd
import xarray as xr
from pathlib import Path

# --- モデル定義・描画関数紐付け ---
MODEL_CONFIG = {
    "GSM": {
        "patterns": [
            "GSM_GPV_Rjp_Gll0p1deg_L-pall",
            "GSM_GPV_Rjp_Gll0p1deg_Lsurf"
        ],
        "panel_func": "make_gsm_panel",
    },
    "MSM": {
        "patterns": [
            "MSM_GPV_Rjp_L-pall",
            "MSM_GPV_Rjp_Lsurf"
        ],
        "panel_func": "make_msm_panel",
    },
    "LFM": {
        "patterns": [
            "LFM_GPV_Rjp_L-pall",
            "LFM_GPV_Rjp_Lsurf"
        ],
        "panel_func": "make_lfm_panel",   # 例：LFM専用パネル描画関数
    },
    "MSM_LOCAL": {
        "patterns": [
            "MSM_GPV_Rjp_L-pall",
            "MSM_GPV_Rjp_Lsurf"
        ],
        "panel_func": "make_msm_local_panel",
    }
    # 必要に応じて拡張
}

GPV_MIRROR_URLS = [
    "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
]

def download_gpv_panel(patterns, base_dir, init_dt, mirror_urls, ncols=12):
    """
    各パターン・時刻のGRIB2ファイルを自動ダウンロード
    欠損があってもNone埋めで返す
    """
    out_list = []
    for i in range(ncols):
        t = init_dt + timedelta(hours=3*i)
        ymdh = t.strftime("%Y%m%d%H")
        col = []
        for pattern in patterns:
            fname = f"Z__C_RJTD_{ymdh}0000_{pattern}_FD0000-0100_grib2.bin"
            fpath = os.path.join(base_dir, fname)
            if not os.path.exists(fpath) or os.path.getsize(fpath) < 10000:
                ok = False
                for url_base in mirror_urls:
                    y, m, d = t.strftime("%Y"), t.strftime("%m"), t.strftime("%d")
                    url = f"{url_base}/{y}/{m}/{d}/{fname}"
                    try:
                        urllib.request.urlretrieve(url, fpath)
                        if os.path.exists(fpath) and os.path.getsize(fpath) > 10000:
                            ok = True
                            print(f"[OK] DL: {fpath}")
                            break
                    except Exception as e:
                        print(f"[NG] {url.split('/')[-1]}: {e}")
                if not ok:
                    col.append(None)
                    continue
            col.append((fpath, t))
        out_list.append(col if all(col) else None)
    return out_list

def get_gpv_nodata_times(init_dt, ncols=12):
    return [init_dt + timedelta(hours=3*i) for i in range(ncols)]

def run_gpv_panel_job(
    model_name: str,
    init_dt: pd.Timestamp,
    base_dir: str = "./data",
    ncols: int = 12,
    out_path: str = None
):
    """
    モデル名でパターン選択・ダウンロード・cfgrib展開・描画まで全自動
    """
    import module.panel_utils as putils  # パネル関数セット
    config = MODEL_CONFIG[model_name]
    patterns = config["patterns"]
    panel_func_name = config["panel_func"]

    # DL
    panel_files = download_gpv_panel(patterns, base_dir, init_dt, GPV_MIRROR_URLS, ncols=ncols)
    valid_files = [f for f in panel_files if f and None not in f]
    if not valid_files or len(valid_files) < 2:
        print("[NO DATA] 2層揃う時刻が見つからず。ダミーパネル生成")
        putils.make_nodata_weather_panel(get_gpv_nodata_times(init_dt, ncols), save_path=out_path or "nodata.jpg")
        return None

    # cfgribでデータセット展開→merge
    ds_list = []
    for files in valid_files:
        sub_ds_list = []
        for path, _ in files:
            try:
                ds = xr.open_dataset(path, engine="cfgrib", filter_by_keys={'stepType': 'instant'})
                sub_ds_list.append(ds)
            except Exception as e:
                print(f"[SKIP] GRIB2 open失敗: {path} ({e})")
        if len(sub_ds_list) == len(patterns):
            ds_merged = xr.merge(sub_ds_list, compat="override", join="outer")
            ds_list.append(ds_merged)
    if not ds_list or len(ds_list) < 2:
        print("[NO DATA] ds_list少なすぎ")
        putils.make_nodata_weather_panel(get_gpv_nodata_times(init_dt, ncols), save_path=out_path or "nodata.jpg")
        return None

    # アライン＆結合
    ds_list_aligned = putils.align_datasets_common(ds_list)
    ds = xr.concat(ds_list_aligned, dim="time")
    times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:ncols]]

    # パネル描画関数呼び分け
    panel_func = getattr(putils, panel_func_name)
    panel_func(ds, times, out_path or f"{model_name.lower()}_panel.jpg")

    return out_path or f"{model_name.lower()}_panel.jpg"

# ======= 単体実行テスト例 =======
if __name__ == "__main__":
    # モデル名は "GSM", "MSM", "MSM_LOCAL" など
    model = "MSM"
    now = pd.Timestamp.now().replace(hour=0, minute=0, second=0, microsecond=0)
    save_path = run_gpv_panel_job(
        model_name=model,
        init_dt=now,
        base_dir="./data",
        ncols=12,
        out_path=f"{model.lower()}_weather_map.jpg"
    )
    print("[完了] 生成ファイル:", save_path)
