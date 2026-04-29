# scripts/seed_cartopy_cache.py
# Cartopy の Natural Earth データを事前ダウンロードしてローカルキャッシュに溜める。
# GitHub Actions では ~/.local/share/cartopy が actions/cache 対象なので、
# このスクリプトを一度実行すれば以後はダウンロード不要＝高速化。

import os
import cartopy
from cartopy.io import shapereader as shp

# 任意：明示しておく（標準もここ）
data_dir = os.path.expanduser("~/.local/share/cartopy")
os.makedirs(data_dir, exist_ok=True)
cartopy.config['data_dir'] = data_dir
print(f"[INFO] cartopy data_dir = {cartopy.config['data_dir']}")

# Natural Earth でよく使うものを“触って”DLさせる
targets = [
    # 物理（海岸線/河川/湖）
    ("physical", "coastline"),
    ("physical", "rivers_lake_centerlines"),
    ("physical", "lakes"),
    # 行政境界
    ("cultural", "admin_0_boundary_lines_land"),
    ("cultural", "admin_0_countries"),
    ("cultural", "admin_1_states_provinces_lines"),
]

# 解像度はあなたの使用状況に合わせて。50m/110m を落としておくと汎用的。
resolutions = ["110m", "50m"]

for res in resolutions:
    for cat, name in targets:
        try:
            path = shp.natural_earth(resolution=res, category=cat, name=name)
            # 実際に open してキャッシュ内にファイルを確実に作らせる
            reader = shp.Reader(path)
            _ = len(list(reader.geometries()))
            print(f"[OK] {res}/{cat}/{name} → cached")
        except Exception as e:
            print(f"[WARN] {res}/{cat}/{name} → {e}")

print("[DONE] seed completed")
