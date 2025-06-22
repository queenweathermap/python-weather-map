# ===============================================
# python-weather-map用 Dockerfile（GRIB2直接処理/Slack通知対応）
# ===============================================

FROM continuumio/miniconda3

# --- 必須パッケージ一発で ---
RUN conda install -c conda-forge python=3.11 eccodes cfgrib cartopy xarray pandas numpy matplotlib metpy scipy requests python-dotenv slack_sdk google-api-python-client google-auth-httplib2 google-auth beautifulsoup4 ipython

# --- 日本語フォント ---
RUN apt-get update && apt-get install -y fonts-ipafont-gothic

WORKDIR /workspace
COPY . /workspace

CMD ["bash"]
