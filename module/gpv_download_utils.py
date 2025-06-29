# ===============================================================
# module/gpv_download_utils.py
# GPV複数ファイルのペアDL/検証・イニシャル最新探索ユーティリティ
# MSM・GSM・LFMも柔軟対応
# 2025-06-29 ChatGPT
# ===============================================================

def find_latest_matched_pairs(
    periods, base_dir, mirrors,
    l_pall_prefix="MSM_GPV_Rjp_L-pall",
    lsurf_prefix="MSM_GPV_Rjp_Lsurf",
    download_func=None
):
    """
    各FH帯ごとにL-pall/Lsurfの両方DLできたペアだけを返す
    download_funcは引数 (pattern, base_dir, mirrors) で呼び出されるDL関数
    戻り値：[(l_pall_grib2, lsurf_grib2, init_time, fh_band), ...]
    """
    matched = []
    for fh in periods:
        l_pall_pattern = f"{l_pall_prefix}_{fh}"
        lsurf_pattern  = f"{lsurf_prefix}_{fh}"
        l_pall_path, itime1 = download_func(l_pall_pattern, base_dir, mirrors)
        lsurf_path, itime2  = download_func(lsurf_pattern, base_dir, mirrors)
        # 両方DLできて、初期時刻が一致するものだけ採用
        if l_pall_path and lsurf_path and itime1 == itime2 and itime1 is not None:
            matched.append((l_pall_path, lsurf_path, itime1, fh))
    return matched

# 追加: GSM/任意モデルに汎用化した「イニシャル最新ファイルを返す」関数
def find_latest_available_files_for_model(
    base_dir, 
    mirrors,
    model_patterns,
    fh_band="FD0000-0100",   # GSM例
    cycle_hours=[0, 21, 18, 15, 12, 9, 6, 3],
    days_back=2,
    list_files_func=None
):
    """
    指定モデルパターン・FH帯でイニシャル最新ペアを返す
    model_patterns: ["GSM_GPV_Rjp_Gll0p1deg_L-pall", ...]
    list_files_func: (datetime, pattern, fh_band) -> ファイル名リスト
    """
    import os
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    for day_delta in range(days_back):
        day = now - timedelta(days=day_delta)
        for h in cycle_hours:
            dt = day.replace(hour=h, minute=0, second=0, microsecond=0)
            found_files = []
            for pattern in model_patterns:
                files = list_files_func(dt, pattern, fh_band)
                if not files:
                    break
                fname = files[0]
                found_files.append(fname)
            if len(found_files) == len(model_patterns):
                y, m, d, hh = dt.strftime("%Y %m %d %H").split()
                base_url = mirrors[0]
                data_url = f"{base_url}/{y}/{m}/{d}/"
                file_infos = [
                    {"url": f"{data_url}{fname}", "local": os.path.join(base_dir, fname)}
                    for fname in found_files
                ]
                return y+m+d, hh, file_infos
    raise FileNotFoundError("利用可能なモデルGPVファイルがindex.html上に見つかりません")
