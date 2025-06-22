# gpv_downloader.py
# ===============================================================
# index.htmlパース型GPVファイル自動ダウンロード＆パネル描画
# MSM/GSM/LFM/ローカル全対応（404回避！）
# 2025-06-22 改訂 by ChatGPT
# ===============================================================

import os
import urllib.request
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd
import xarray as xr
from pathlib import Path

# --- モデル・パターン定義 ---
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
        "panel_func": "make_lfm_panel",
    },
    "MSM_LOCAL": {
        "patterns": [
            "MSM_GPV_Rjp_L-pall",
            "MSM_GPV_Rjp_Lsurf"
        ],
        "panel_func": "make_msm_local_panel",
    }
}

GPV_MIRROR_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"

def list_files_on_server(date: datetime, pattern: str, fh: str):
    """
    サーバのindex.htmlをパースして該当ファイルリストを返す
    """
    y, m, d = date.strftime("%Y"), date.strftime("%m"), date.strftime("%d")
    url = f"{GPV_MIRROR_URL}/{y}/{m}/{d}/"
    try:
        with urllib.request.urlopen(url) as res:
            soup = BeautifulSoup(res.read(), "html.parser")
            files = [
                a["href"] for a in soup.find_all("a", href=True)
                if pattern in a["href"] and fh in a["href"] and a["href"].endswith("grib2.bin")
            ]
            return files
    except Exception as e:
        print(f"[WARN] index.html取得失敗: {url} ({e})")
        return []

def find_latest_available_gpv(pattern, fh_list):
    """
    サーバで実在する最新ファイルを探索し返す
    """
    now = datetime.utcnow() + timedelta(hours=9)
    for day_offset in range(0, 3):
        dt = now - timedelta(days=day_offset)
        for h in [0, 3, 6, 9, 12, 15, 18, 21]:
            for fh in fh_list:
                files = list_files_on_server(dt, pattern, fh)
                if files:
                    fname = sorted(files)[-1]
                    print(f"[FOUND] {fname}")
                    y, m, d = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
                    url = f"{GPV_MIRROR_URL}/{y}/{m}/{d}/{fname}"
                    return url, fname, dt
    print(f"[ERROR] {pattern}でファイル見つからず")
    return None, None, None

def download_gpv_by_index(model="MSM", base_dir="./data", fh_list=None):
    """
    index.htmlからサーバ実在ファイルだけを自動DL
    """
    if fh_list is None:
        fh_list = ["FH00-15", "FH16-33", "FH34-39", "FH40-51", "FH52-78"]
    patterns = MODEL_CONFIG[model]["patterns"]
    results = []
    for pattern in patterns:
        url, fname, dt = find_latest_available_gpv(pattern, fh_list)
        if url:
            os.makedirs(base_dir, exist_ok=True)
            out_path = os.path.join(base_dir, fname)
            try:
                urllib.request.urlretrieve(url, out_path)
                print(f"[OK] DL: {out_path}")
                results.append((out_path, dt))
            except Exception as e:
                print(f"[NG] {fname}: {e}")
                results.append((None, dt))
        else:
            results.append((None, None))
    return results

def get_gpv_nodata_times(init_dt, ncols=12):
    return [init_dt + timedelta(hours=3 * i) for i in range(ncols)]

def run_gpv_panel_job(
    model_name: str,
    base_dir: str = "./data",
    ncols: int = 12,
    out_path: str = None
):
    """
    パターン自動選択＆index.html探索型で最新ファイルDL→パネル描画
    """
    import module.panel_utils as putils  # パネル関数セット
    config = MODEL_CONFIG[model_name]
    fh_list = ["FH00-15", "FH16-33", "FH34-39", "FH40-51", "FH52-78"]

    # index.htmlを使いファイル実在チェック＆DL
    dl_files = download_gpv_by_index(model=model_name, base_dir=base_dir, fh_list=fh_list)
    valid_files = [f for f, _ in dl_files if f is not None]
    if len(valid_files) < len(config["patterns"]):
        print("[NO DATA] 必要ファイル揃わずダミーパネル生成")
        putils.make_nodata_weather_panel(get_gpv_nodata_times(pd.Timestamp.now(), ncols), save_path=out_path or "nodata.jpg")
        return None

    # cfgribでデータセット展開→merge
    ds_list = []
    for path, _ in dl_files:
        if path:
            try:
                ds = xr.open_dataset(path, engine="cfgrib", filter_by_keys={'stepType': 'instant'})
                ds_list.append(ds)
            except Exception as e:
                print(f"[SKIP] GRIB2 open失敗: {path} ({e})")
    if len(ds_list) < len(config["patterns"]):
        print("[NO DATA] ds_list少なすぎ")
        putils.make_nodata_weather_panel(get_gpv_nodata_times(pd.Timestamp.now(), ncols), save_path=out_path or "nodata.jpg")
        return None

    # 必要ならアライン
    ds_merged = xr.merge(ds_list, compat="override", join="outer")
    # 時刻軸処理など必要ならここで追加
    times = get_gpv_nodata_times(pd.Timestamp.now(), ncols)  # 仮
    panel_func = getattr(putils, config["panel_func"])
    panel_func(ds_merged, times, out_path or f"{model_name.lower()}_panel.jpg")
    return out_path or f"{model_name.lower()}_panel.jpg"

# ======= 単体実行テスト例 =======
if __name__ == "__main__":
    # モデル名は "GSM", "MSM", "LFM", "MSM_LOCAL" など
    model = "MSM"
    save_path = run_gpv_panel_job(
        model_name=model,
        base_dir="./data",
        ncols=12,
        out_path=f"{model.lower()}_weather_map.jpg"
    )
    print("[完了] 生成ファイル:", save_path)
