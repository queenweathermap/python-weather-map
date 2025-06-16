# python-weather-map

# GPV Project

このプロジェクトは、気象庁の数値予報（GPV）データを処理・可視化するためのJupyterノートブックとモジュール群です。

## 📁 ディレクトリ構成

📁 .github/workflows/
├── daily_weather.yml          # 全国＋秋田（現状）
├── daily_weather_akita.yml    # 秋田のみ（新規）

📁 module/
├── drive_utils.py
├── slack_utils.py
...

📁 data/
...

gpv_panel_daily_local.py         ← 任意地域用（CLI）
gpv_panel_daily_local_akita.py   ← 秋田専用描画スクリプト
main_weather_batch.py            ← 全体まとめ
main_weather_akita.py            ← 秋田専用
requirements.txt

```

## ✅ モジュールの使い方（例: ノートブック先頭に記述）

```python
import sys
sys.path.append("./module")

from gpvutils import download_data, load_dataset
from gpv_downloader import download_msm_data
```

## 🚀 使用手順

1. GRIB2データをダウンロード
2. NetCDFに変換
3. xarrayで読み込み
4. 可視化モジュールでプロット

## 🔧 対応モデル

- MSM
- GSM

## 📌 依存ライブラリ（例）

- xarray
- numpy
- matplotlib
- cartopy
- wgrib2（外部コマンド）

