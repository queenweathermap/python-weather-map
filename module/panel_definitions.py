# module/panel_definitions.py
# ===============================================
# 天気図パネル定義（全国・秋田・任意エリア）
# 各エリアごとに panel_def を返す関数群
# ===============================================


# --- 地域ごとのデフォルトズーム範囲定義 ---
REGION_EXTENTS = {
    "japan": [122, 153, 20, 46],
    "akita": [139.5, 141.0, 38.8, 40.5],
    "tokyo": [138.5, 140.0, 34.7, 36.2],
    # 必要に追加
}

def get_panel_def_japan(ds_isobaric, ds_surf_instant):
    """
    全国（8段パネル）用 panel_def
    """
    from module.plot.plot_300hpa_height_wind import plot_300hpa_height_wind
    from module.plot.plot_500hpa_vorticity import plot_500hpa_vorticity
    from module.plot.plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp
    from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
    from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
    from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
    from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
    from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm
    """
    全国パネル用・描画構成定義
    ds_gsm_isobaric: GSM等圧面データセット
    ds_msm_isobaric: MSM等圧面データセット
    ds_msm_surf_instant: MSM地上データセット
    """
    return [
        (plot_300hpa_height_wind, ds_gsm_isobaric, "300hPa高度・風"),
        (plot_500hpa_vorticity, ds_gsm_isobaric, "500hPa渦度"),
        (plot_700hpa_dindex_500hpa_temp, ds_gsm_isobaric, "700hPa湿数+500hPa気温"),
        (plot_850hpa_temp_wind_700hpa_w, ds_msm_isobaric, "850hPa温度・風+700hPa鉛直流"),
        (plot_850hpa_thetae_stream, ds_msm_isobaric, "850hPa θe流線"),
        (plot_975hpa_temp_wind_dindex, ds_msm_isobaric, "975hPa温度・風・湿数"),
        (plot_925hpa_temp_wind_dindex, ds_msm_isobaric, "925hPa温度・風・湿数"),
        (plot_surface_pressure_and_wind_msm, ds_msm_surf_instant, "地上気圧・風・降水量"),
    ]

def get_panel_def_akita(ds_emagram, ds_850, ds_850_thetae, ds_925, ds_975, ds_surface):
    """
    秋田局地（8段パネル）用 panel_def
    6種類＋空欄1段
    """
    from module.plot.plot_emagram import plot_emagram
    from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
    from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
    from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
    from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
    from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

    return [
        # GSM（上1段）
        (plot_emagram, ds_emagram, "エマグラム"),
        # MSM（下5段）
        (plot_850hpa_temp_wind_700hpa_w, ds_850, "850hPa気温・風・700hPa鉛直流"),
        (plot_850hpa_thetae_stream, ds_850_thetae, "850hPa相当温位・流線"),
        (plot_925hpa_temp_wind_dindex, ds_925, "925hPa気温・風・湿数"),
        (plot_975hpa_temp_wind_dindex, ds_975, "975hPa気温・風・湿数"),
        (plot_surface_pressure_and_wind_msm, ds_surface, "地上"),
        (None, None, ""),  # 7段目空欄
        (None, None, ""),  # 8段目空欄
    ]

# --- 拡張例: 任意ローカル（段数可変・テンプレート化しやすい） ---
def get_panel_def_local(custom_items, total_rows=8):
    """
    任意ローカル局地用（カスタムアイテムリストを受けて7段化）
    custom_items: [(plot_func, ds, title), ...] のリスト（足りない分は空欄で埋める）
    total_rows: 何段構成にするか（デフォルト7段）
    """
    # 空欄分補充
    def_item = (None, None, "")
    result = list(custom_items)
    while len(result) < total_rows:
        result.append(def_item)
    return result[:total_rows]

# --- 公開関数 ---
__all__ = [
    "get_panel_def_japan",
    "get_panel_def_akita",
    "get_panel_def_local",
]

