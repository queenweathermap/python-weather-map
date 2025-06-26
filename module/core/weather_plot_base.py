# module/core/weather_plot_base.py
# ===============================================
# 天気図プロット共通基底クラス（将来拡張用/推奨）
# 全plot共通ベース（地図投影や色調整など）
# 2025-06-27 by ChatGPT
# ===============================================
class WeatherPlotBase:
    """天気図描画クラス基底（テンプレート・拡張前提）"""
    def __init__(self, ds):
        self.ds = ds

    def plot(self, ax, step=0):
        """サブクラスで必ず実装"""
        raise NotImplementedError("plot() must be implemented by subclass")

    def get_title(self):
        return "Weather Panel"

