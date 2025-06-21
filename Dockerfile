# Dockerfile
# ===============================================
# python-weather-map用 Dockerfile（Slack通知専用）
# ・wgrib2, 日本語フォント, Miniconda, pipパッケージ
# ・main_weather_batch.py実行
# 2025-06-16 by ChatGPT
# ===============================================

FROM continuumio/miniconda3

RUN conda install -c conda-forge wgrib2 python=3.11

WORKDIR /workspace
COPY . /workspace
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# NetCDFサポート確認
RUN wgrib2 -h | grep netcdf || (echo "NetCDFサポートがありません" && exit 1)

CMD ["bash"]
