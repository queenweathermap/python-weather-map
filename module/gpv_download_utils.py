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

# 追加で「DLできた最新イニシャルで止める」バージョン等も同様に
