# gpv_downloader.py
# ===============================================================
# GPVファイルのダウンロード・自動パネル描画ユーティリティ
# MSM/GSM/LFM/ローカルもモデル名で一括運用（パターン自動分岐＋時刻探索）
# 2025-06-22 by ChatGPT
# ===============================================================

import os
import urllib.request
import glob
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
        "panel_func": "make_lfm_panel",
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

GPV_MIRROR_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
PATTERN = "MSM_GPV_Rjp_Lsurf"
MAX_DAYS = 3

def find_latest_available_init(patterns, base_dir, mirror_urls, hours=[0, 12, 18, 6], max_days=2):
    """
    サーバ上で利用可能な最新のinit_dt（イニシャル時刻）を探索
    """
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    for day_offset in range(max_days + 1):
        dt = now - pd.Timedelta(days=day_offset)
        for hour in sorted(hours, reverse=True):  # 18→12→6→0の順で探索
            dt_h = dt.replace(hour=hour)
            # パターンごとにファイルURL組み立て
            all_exist = True
            for pattern in patterns:
                ymd = dt_h.strftime("%Y%m%d")
                h = dt_h.strftime("%H")
                # MSM系は複数stepまとめファイルなので、サーバで実在チェック
                fname = f"Z__C_RJTD_{ymd}{h}0000_{pattern}_FH00-15_grib2.bin"
                y, m, d = dt_h.strftime("%Y"), dt_h.strftime("%m"), dt_h.strftime("%d")
                url = f"{mirror_urls[0]}/{y}/{m}/{d}/{fname}"
                try:
                    with urllib.request.urlopen(url) as res:
                        if res.status != 200:
                            all_exist = False
                            break
                except Exception:
                    all_exist = False
                    break
            if all_exist:
                print(f"[INFO] 使用可能init_dt: {dt_h}")
                return dt_h
    print("[WARN] 有効なinit_dtが見つかりません")
    return None

def download_gpv_panel(patterns, base_dir, init_dt, mirror_urls, ncols=12):
    """
    各パターン・時刻のGRIB2ファイルを自動ダウンロード
    欠損があってもNone埋めで返す
    """
    out_list = []
    for i in range(ncols):
        t = init_dt + timedelta(hours=3 * i)
        ymdh = t.strftime("%Y%m%d%H")
        col = []
        for pattern in patterns:
            # stepまとめファイル：MSM/LFMの場合
            if "MSM" in pattern or "LFM" in pattern:
                fh_start = 0 + 16 * (i // 16)
                fh_end = fh_start + 15
                fname = f"Z__C_RJTD_{ymdh}0000_{pattern}_FH{fh_start:02d}-{fh_end:02d}_grib2.bin"
            else:
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
    return [init_dt + timedelta(hours=3 * i) for i in range(ncols)]

def run_gpv_panel_job(
    model_name: str,
    base_dir: str = "./data",
    ncols: int = 12,
    out_path: str = None
):
    """
    モデル名でパターン選択・ダウンロード・cfgrib展開・描画まで全自動
    最新利用可能イニシャル時刻も自動探索
    """
    import module.panel_utils as putils  # パネル関数セット
    config = MODEL_CONFIG[model_name]
    patterns = config["patterns"]
    panel_func_name = config["panel_func"]

    # 1. 最新利用可能なイニシャル時刻を探索
    init_dt = find_latest_available_init(patterns, base_dir, GPV_MIRROR_URLS)
    if init_dt is None:
        print("[NO DATA] 有効なinit_dtが見つかりません")
        putils.make_nodata_weather_panel(get_gpv_nodata_times(pd.Timestamp.now(), ncols), save_path=out_path or "nodata.jpg")
        return None

    # 2. DL
    panel_files = download_gpv_panel(patterns, base_dir, init_dt, GPV_MIRROR_URLS, ncols=ncols)
    valid_files = [f for f in panel_files if f and None not in f]
    if not valid_files or len(valid_files) < 2:
        print("[NO DATA] 2層揃う時刻が見つからず。ダミーパネル生成")
        putils.make_nodata_weather_panel(get_gpv_nodata_times(init_dt, ncols), save_path=out_path or "nodata.jpg")
        return None

    # 3. cfgribでデータセット展開→merge
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

    # 4. アライン＆結合
    ds_list_aligned = putils.align_datasets_common(ds_list)
    ds = xr.concat(ds_list_aligned, dim="time")
    times = [pd.Timestamp(t).to_pydatetime() for t in ds.time.values[:ncols]]

    # 5. パネル描画関数呼び分け
    panel_func = getattr(putils, panel_func_name)
    panel_func(ds, times, out_path or f"{model_name.lower()}_panel.jpg")

    return out_path or f"{model_name.lower()}_panel.jpg"

def find_latest_msm_surface_file():
    now = datetime.utcnow() + timedelta(hours=9)  # JST
    for day_offset in range(MAX_DAYS):
        dt = now - timedelta(days=day_offset)
        for h in [0, 12]:
            ymd = dt.strftime("%Y%m%d")
            H = f"{h:02d}"
            fname = f"Z__C_RJTD_{ymd}{H}0000_{PATTERN}_FH00-15_grib2.bin"
            y, m, d = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
            url = f"{GPV_MIRROR_URL}/{y}/{m}/{d}/{fname}"
            try:
                with urllib.request.urlopen(url) as res:
                    if res.status == 200:
                        print("[FOUND]", url)
                        return url, fname
            except Exception:
                continue
    print("[ERROR] MSMファイルが見つかりません")
    return None, None

# 実際のダウンロード
url, fname = find_latest_msm_surface_file()
if url:
    urllib.request.urlretrieve(url, f"./data/{fname}")
    print("[OK] DL:", fname)


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
