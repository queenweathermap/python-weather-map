# Dockerfile
# ===============================================
# python-weather-map用 Dockerfile（Slack通知専用）
# ・wgrib2, 日本語フォント, Miniconda, pipパッケージ
# ・main_weather_batch.py実行
# 2025-06-16 by ChatGPT
# ===============================================

FROM ubuntu:22.04

# ---- 依存インストール ----
RUN apt-get update && \
    apt-get install -y \
      wget git bzip2 \
      python3 python3-pip \
      build-essential python3-dev libfreetype6-dev pkg-config \
      libcrypt1 \
      fonts-ipafont-gothic \
      libnetcdf-dev netcdf-bin

# ---- wgrib2 NetCDFサポート付きビルド ----
RUN wget https://ftp.cpc.ncep.noaa.gov/wd51we/wgrib2/wgrib2.tgz && \
    tar xzf wgrib2.tgz && \
    cd grib2 && \
    make && \
    cp ./wgrib2/wgrib2 /usr/local/bin/ && \
    cd .. && rm -rf grib2 wgrib2.tgz

# --- NetCDFサポート確認 ---
RUN wgrib2 -h | grep netcdf

WORKDIR /workspace

COPY . /workspace

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

CMD ["python3", "main_weather_batch.py"]
