# ===============================================
# module/gpv_plotter_msm.py
# MSMモデル用 可視化関数まとめimportモジュール
# ===============================================
# MSM GPVデータを扱う全描画関数は「ここでimport・管理」してください
# ・外部から直接個別モジュールimportは禁止
# ・新規追加・廃止もこのファイル経由に徹底
# ・関数名は「_msm」付きで統一（GSMと混在事故防止）
# ・サンプル（2025-06-xx ChatGPT自動整備）
# ===============================================

from .plot_300hpa_height_wind import plot_300hpa_height_wind_msm
from .plot_500hpa_vorticity import plot_500hpa_vorticity_msm
from .plot_700hpa_dindex_500hpa_temp import plot_700hpa_dindex_500hpa_temp_msm
from .plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w_msm
from .plot_850hpa_thetae_stream import plot_850hpa_thetae_stream_msm
from .plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex_msm
from .plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex_msm
from .plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm
from .plot_emagram import plot_emagram_msm_panel

# === [将来の拡張ルール] ===
# ・ここに記載の無い関数は「公式サポート外」とみなす
# ・新規パネルを追加したら必ずこのファイルにimportを追加
# ・引数や返り値インターフェースも「各plot_XXX.py」側で必ず統一
# ===========================

# MSM用関数は必ず「_msm」付きでimport＆定義！
# 追加・削除時も本ファイルを更新すること
