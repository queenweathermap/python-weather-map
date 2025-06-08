# python-weather-map

# GPV Project

このプロジェクトは、気象庁の数値予報（GPV）データを処理・可視化するためのJupyterノートブックとモジュール群です。

## 📁 ディレクトリ構成

```
gpv_project/
    └── data/
    ├── weather.ipynb  # 各種処理ノートブック
    └── module/
        ├── gpvutils.py
        ├── gpv_downloader.py
        ├── gpv_plotter.py
        └── gpv_plotter_japan.py
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

