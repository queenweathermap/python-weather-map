import os
import xarray as xr
from module.utils.gpv_html_parser import find_existing_msm_files
from module.utils.zip_utils import zip_files
from module.utils.drive_utils import upload_to_drive
from module.utils.slack_utils import send_slack_message
from module.panel_utils import make_local_weather_panel, make_nodata_weather_panel
from module.plot.plot_emagram import plot_emagram
from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm

BASE_DIR = "./data"
OUT_PREFIX = "akita_local_msm_map"
BASE_URL = "https://database.rish.kyoto-u.ac.jp/arch/jmadata/data/gpv/original"
YMD = pd.Timestamp.now().strftime("%Y%m%d")
NCOLS = 4
NROWS = 7  # 全国と揃える場合
NPAGES = 1
CITY_NAME = "Akita City"
PIN_LAT, PIN_LON = 39.72, 140.10  # 秋田市中心

# 1. データファイルを探して xarrayで開く
files = find_existing_msm_files(BASE_URL, YMD)
if not files:
    # データなければNoData画像だけ出力
    make_nodata_weather_panel(
        save_path=f"{OUT_PREFIX}_nodata.jpg",
        city_name=CITY_NAME,
        times=[...]
    )
    raise RuntimeError("No MSM data found")
grib_path = files[0]
ds = xr.open_dataset(grib_path, engine="cfgrib")

# 2. timesリストの生成（例：3hごと4本）
def get_times(n):
    import pandas as pd
    now = pd.Timestamp.now().replace(minute=0, second=0, microsecond=0)
    hour = now.hour
    init_hour = max([h for h in range(0, 24, 3) if h <= hour])
    base_time = now.replace(hour=init_hour)
    return [base_time + pd.Timedelta(hours=3*i) for i in range(n)]
times = get_times(NCOLS)

# 3. プロット関数リスト（全国7段に合わせ、足りない分はNoneで埋めてもOK）
plot_func_list = [
    plot_emagram,
    plot_850hpa_temp_wind_700hpa_w,
    plot_850hpa_thetae_stream,
    plot_925hpa_temp_wind_dindex,
    plot_975hpa_temp_wind_dindex,
    plot_surface_pressure_and_wind_msm,
    None,  # 7段目のために空き（将来追加も可能）
]

# 4. パネル画像生成（1ページのみなら1ループ）
panel_imgs = []
for page in range(NPAGES):
    out_img = f"{OUT_PREFIX}_p{page+1}.jpg"
    make_local_weather_panel(
        ds, times, out_img,
        pin_lat=PIN_LAT, pin_lon=PIN_LON, city_name=CITY_NAME,
        lat_range=(38, 41), lon_range=(139, 142),
        plot_func_list=plot_func_list,
        nrows=NROWS, ncols=NCOLS,
    )
    panel_imgs.append(os.path.join(BASE_DIR, out_img))

# 5. ZIP圧縮・Driveアップロード・Slack通知は全国版と同じでOK
        # --- ZIP作成 ---
        zip_name = f"{OUT_PREFIX}.zip"
        zip_path = os.path.join(BASE_DIR, zip_name)
        print("[STEP3] JPGをZIP圧縮")
        zip_files(panel_imgs, zip_path)
        print(f"[OK] ZIP作成: {zip_path}")

        # --- Drive & Slack通知 ---
        print("[STEP4] Google Driveへアップロード")
        drive_url = upload_to_drive(zip_path)
        print(f"[OK] Drive URL: {drive_url}")

        # --- ファイルリスト＆Slack通知 ---
        file_log = "\n".join([os.path.basename(p) for p in panel_imgs] + [zip_name])
        detail_log = log_buffer.getvalue()
        msg = (
                f":large_red_circle: 秋田局地MSM天気図パネル {pd.Timestamp.now():%Y%m%d %H:%M}\n"
            "--- LOG ---\n"
            f"{file_log}\n"
            "--- 詳細LOG ---\n"
            f"{detail_log[-1800:]}"
        )
        send_slack_message(msg)

    except Exception as e:
        print("NO DATA: Exception", e)
        traceback.print_exc()
        print("=== EXCEPTION CAUGHT ===")
        print(traceback.format_exc())
        raise
        make_nodata_weather_panel(
            save_path=f"{OUT_PREFIX}_nodata.jpg",
            city_name=CITY_NAME,
            times=get_gpv_nodata_times(NCOLS)
        )
        sys.exit(1)
    finally:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        log_buffer.close()

if __name__ == "__main__":
    main()
