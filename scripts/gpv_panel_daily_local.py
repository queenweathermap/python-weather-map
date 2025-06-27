# scripts/gpv_panel_daily_morioka.py
import os
from module.plotter.gpv_plotter_universal import generate_universal_panel_and_notify
from module.plot.plot_emagram import plot_emagram
from module.plot.plot_850hpa_temp_wind_700hpa_w import plot_850hpa_temp_wind_700hpa_w
from module.plot.plot_850hpa_thetae_stream import plot_850hpa_thetae_stream
from module.plot.plot_925hpa_temp_wind_dindex import plot_925hpa_temp_wind_dindex
from module.plot.plot_975hpa_temp_wind_dindex import plot_975hpa_temp_wind_dindex
from module.plot.plot_surface_pressure_wind_precip import plot_surface_pressure_and_wind_msm
from module.utils.slack_utils import send_slack_text

def main():
    import datetime
    now = datetime.datetime.utcnow()
    ymd = now.strftime("%Y%m%d")
    hh = f"{(now.hour//3)*3:02d}"

    output_dir = "./data"
    drive_folder = os.environ["DRIVE_FOLDER_ID"]
    slack_channel = os.environ["SLACK_CHANNEL_ID"]
    city_name = "morioka"

    panel_def = [
        (plot_emagram, None, "エマグラム"),
        (plot_850hpa_temp_wind_700hpa_w, None, "850hPa温度・風＋700hPa鉛直流"),
        (plot_850hpa_thetae_stream, None, "850hPa相当温位・流線"),
        (plot_925hpa_temp_wind_dindex, None, "925hPa温度・風・湿数"),
        (plot_975hpa_temp_wind_dindex, None, "975hPa温度・風・湿数"),
        (plot_surface_pressure_and_wind_msm, None, "地上気圧・風・降水"),
        (None, None, "未使用"),
    ]

    panel_imgs, zip_path, drive_url = generate_universal_panel_and_notify(
        ymd=ymd, hh=hh,
        model="MSM",
        output_dir=output_dir,
        drive_folder=drive_folder,
        ncols=4, npages=1, nrows=7,
        panel_def=panel_def,
        lat_range=(38.5, 40.5), lon_range=(140.5, 142), # 盛岡周辺例
        pin_lat=39.7, pin_lon=141.15,
        city_name=city_name,
        slack_channel=slack_channel,
    )

    file_log = "\n".join([os.path.basename(p) for p in panel_imgs] + [os.path.basename(zip_path)])
    msg = (
        f":cityscape: 盛岡局地パネル {ymd} UTC{hh}\n"
        "--- LOG ---\n"
        f"{file_log}\n"
        f"{drive_url}"
    )
    send_slack_text(channel=slack_channel, message=msg)

if __name__ == "__main__":
    main()
