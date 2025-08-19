# ===============================================================
# module/panel_definitions.py
# パネル定義関数（dict＋step方式・全国/局地テンプレ化）
# 2025-07-01 ChatGPT
# ===============================================================

REGION_EXTENTS = {
    "japan": [122, 153, 20, 46],
    "akita": [139.5, 141.0, 38.8, 40.5],
    "tokyo": [138.5, 140.0, 34.7, 36.2],
}

# module/panel_definitions.py
def get_panel_def_japan(var_dict):
    """
    全国6段パネル定義（JPG1枚=1step分で呼ぶ用）
    var_dict: そのstep分の変数dict
      例: {"gh_300": <DataArray>, ...}
    """
    from module.plot.plot_300hpa_height_wind import plot_300hpa_height_wind
    from module.plot.plot_500hpa_vorticity import plot_500hpa_vorticity
    from module.plot.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
    from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
    from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
    from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

    return [
        # 1段目: 300hPa高度・風
        (plot_300hpa_height_wind, {
            "h": var_dict.get("gh_300"),
            "u": var_dict.get("u_300"),
            "v": var_dict.get("v_300"),
        }, "300hPa高度・風"),
        # 2段目: 500hPa渦度
        (plot_500hpa_vorticity, {
            "h": var_dict.get("gh_500"),
            "u": var_dict.get("u_500"),
            "v": var_dict.get("v_500"),
        }, "500hPa渦度"),
        # 3段目: 700hPa湿数＋500hPa気温
        (plot_700hpa_dindex_500hpa_temp, {
            "t_700": var_dict.get("t_700"),
            "r_700": var_dict.get("r_700"),
            "t_500": var_dict.get("t_500"),
        }, "700hPa湿数+500hPa気温"),
        # 4段目: 850hPa温度・風＋700hPa鉛直流
        (plot_850hpa_temp_wind_700hpa_w, {
            "t_850": var_dict.get("t_850"),
            "u_850": var_dict.get("u_850"),
            "v_850": var_dict.get("v_850"),
            "w_700": var_dict.get("w_700"),
        }, "850hPa温度・風+700hPa鉛直流"),
        # 5段目: 850hPa θe流線
        (plot_850hpa_thetae_stream, {
            "t_850": var_dict.get("t_850"),
            "r_850": var_dict.get("r_850"),
            "u_850": var_dict.get("u_850"),
            "v_850": var_dict.get("v_850"),
        }, "850hPa θe流線"),
        # 6段目: 地上気圧・風・降水量
        (plot_surface_pressure_and_wind_msm, {
            "prmsl": var_dict.get("prmsl"),
            "u10":   var_dict.get("u10"),
            "v10":   var_dict.get("v10"),
          # "apcp":  var_dict.get("apcp"),
        }, "地上気圧・風・降水量"),
    ]

def get_panel_def_akita(var_dict):
    """
    秋田局地用パネル定義（panel_datasets で用意した個別キーを束ねて渡す）
    """
    from module.plot.plot_emagram import plot_emagram
    from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
    from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
    from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
    from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
    from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

    rows = []

    # 1段目：エマグラム（あれば）
    if var_dict.get("emagram") is not None:
        rows.append((plot_emagram, {"emagram": var_dict.get("emagram")}, "エマグラム"))
    else:
        rows.append((None, None, ""))  # 無ければ空欄

    # 2段目：850hPa 気温・風 + 700hPa 鉛直流
    rows.append((
        plot_850hpa_temp_wind_700hpa_w,
        {
            "t_850": var_dict.get("t_850"),
            "u_850": var_dict.get("u_850"),
            "v_850": var_dict.get("v_850"),
            "w_700": var_dict.get("w_700"),
        },
        "850hPa気温・風・700hPa鉛直流"
    ))

    # 3段目：850hPa θe 流線
    rows.append((
        plot_850hpa_thetae_stream,
        {
            "t_850": var_dict.get("t_850"),
            "r_850": var_dict.get("r_850"),
            "u_850": var_dict.get("u_850"),
            "v_850": var_dict.get("v_850"),
        },
        "850hPa相当温位・流線"
    ))

    # 4段目：925hPa（用意できるなら）
    rows.append((
        plot_925hpa_temp_wind_dindex,
        {
            "t_925": var_dict.get("t_925"),
            "r_925": var_dict.get("r_925"),
            "u_925": var_dict.get("u_925"),
            "v_925": var_dict.get("v_925"),
        },
        "925hPa気温・風・湿数"
    ))

    # 5段目：975hPa（用意できるなら）
    rows.append((
        plot_975hpa_temp_wind_dindex,
        {
            "t_975": var_dict.get("t_975"),
            "r_975": var_dict.get("r_975"),
            "u_975": var_dict.get("u_975"),
            "v_975": var_dict.get("v_975"),
        },
        "975hPa気温・風・湿数"
    ))

    # 6段目：地上
    rows.append((
        plot_surface_pressure_and_wind_msm,
        {
            "prmsl": var_dict.get("prmsl"),
            "u10":   var_dict.get("u10"),
            "v10":   var_dict.get("v10"),
            # "apcp":  var_dict.get("apcp"),  # 必要なら有効化
        },
        "地上気圧・風・降水量"
    ))

    # 7・8段目は空欄でパディング
    rows.append((None, None, ""))
    rows.append((None, None, ""))
    return rows


def get_panel_def_local(var_items, total_rows=8):
    """
    任意ローカル局地用（カスタムアイテムリストを受けて段数可変）
    var_items: [(plot_func, ds_dict, title), ...] のリスト（不足分は空欄で埋める）
    """
    def_item = (None, None, "")
    result = list(var_items)
    while len(result) < total_rows:
        result.append(def_item)
    return result[:total_rows]

# --- 公開関数 ---
__all__ = [
    "get_panel_def_japan",
    "get_panel_def_akita",
    "get_panel_def_local",
    "REGION_EXTENTS",
]
