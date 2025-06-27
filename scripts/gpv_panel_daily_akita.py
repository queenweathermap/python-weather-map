# gpv_panel_daily_akita.py
# ===============================================================
# 秋田局地MSMパネル（エマグラム付き）自動生成スクリプト
# ---------------------------------------------------------------
# ・RISH GPVデータ（MSM）を最新公開分で自動ダウンロード
# ・「存在する最新」ディレクトリ/ファイルを自動判定
# ・GPVファイルがなければサイクル遡りで取得
# ・描画後はGoogle Drive/Slackへ自動通知（既存モジュール利用）
# ---------------------------------------------------------------
# 2025-06-27 by ChatGPT
# ===============================================================

import sys
import traceback
import os
import datetime
import requests

# ---- モジュール読み込み（※既存プロジェクトのまま） ----
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify

# === 定数（環境に応じて変更） ===
BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
CYCLE_HOURS = [21, 18, 15, 12, 9, 6, 3, 0]  # MSMサイクル（遡り探索用）

def find_latest_available_files(base_url=BASE_URL, max_days=2):
    """利用可能な最新のファイル一式（パスリスト）を返す。なければ遡る。"""
    now = datetime.datetime.utcnow()
    for day_delta in range(max_days):
        day = now - datetime.timedelta(days=day_delta)
        for h in CYCLE_HOURS:
            t = day.replace(hour=h, minute=0, second=0, microsecond=0)
            y, m, d, hh = t.strftime("%Y %m %d %H").split()
            data_url = f"{base_url}/{y}/{m}/{d}/"
            target_init = f"{y}{m}{d}{hh}0000"

            file_patterns = [
                f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin",
                f"Z__C_RJTD_{target_init}_MSM_GPV_Rjp_Lsurf_FH00-15_grib2.bin"
            ]
            file_paths = []
            found = False

            for fname in file_patterns:
                url = f"{data_url}{fname}"
                r = requests.head(url, timeout=5)
                if r.status_code == 200:
                    found = True
                    # ここではまだダウンロードせず、戻り値としてURL情報を返す
                    file_paths.append({"url": url, "local": os.path.join("./data", fname)})

            if found:
                # 1つでも見つかったら（両方404なら前サイクルへ）
                return y, m, d, hh, file_paths

    raise FileNotFoundError("利用可能なGPVファイルが見つかりません")

def main():
    try:
        y, m, d, hh, file_infos = find_latest_available_files()
        print(f"[INFO] 利用可能サイクル: {y}/{m}/{d} {hh}UTC")
        downloaded = []
        for info in file_infos:
            print(f"[INFO] ダウンロード: {info['url']}")
            resp = requests.get(info['url'])
            if resp.status_code == 200:
                os.makedirs(os.path.dirname(info['local']), exist_ok=True)
                with open(info['local'], "wb") as f:
                    f.write(resp.content)
                print(f"[OK] 保存: {info['local']}")
                downloaded.append(info['local'])

        if not downloaded:
            raise FileNotFoundError("GPVファイルが見つかりません")

        # 必要な天気図パネル生成処理へ（既存のまま）
        panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
            ymd=ymd,
            hh=hh,
            model=model,
            output_dir=output_dir,
        )
        print("[OK] 秋田局地パネル生成・通知完了")
        print(f"Drive URL: {drive_url}")

    except Exception as e:
        print(f"[ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
