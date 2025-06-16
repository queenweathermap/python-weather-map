# module/gpv_download_utils.py
# --------------------------------------------------------
# GPVの**複数ファイルをペアや日単位でまとめてDL/検証する運用ユーティリティ**
# ・各時間帯やFH帯をループし、L-pall/Lsurf両方DLできたものだけ返す
# ・引数やパターン名でGSMもMSMも柔軟対応
# --------------------------------------------------------

def find_latest_matched_pairs(periods, base_dir, mirrors,
                             l_pall_prefix="MSM_GPV_Rjp_L-pall",
                             lsurf_prefix="MSM_GPV_Rjp_Lsurf",
                             download_func=None):
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
