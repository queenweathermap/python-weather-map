# ===============================================
# 秋田パネル用 Dockerfile（GRIB2直接処理/Slack通知対応）
# ===============================================

# requirements.txt が 3.10 でピン留めされている想定なので 3.10 を使います
FROM python:3.10-slim

# Cartopy / cfgrib / pdf2image に必要なシステム依存ライブラリ
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential gfortran \
    proj-bin libproj-dev libgeos-dev \
    libeccodes0 libeccodes-dev \
    libnetcdf-dev libhdf5-dev \
    poppler-utils \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
# requirements.txt に無いが GCS へアップロードするために必要なクライアントを追加で入れる
RUN pip install --no-cache-dir -r requirements.txt google-cloud-storage

# （必要なら日本語フォント）
# RUN apt-get update && apt-get install -y fonts-noto-cjk && rm -rf /var/lib/apt/lists/*

# 追記（任意だが推奨）
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    MPLCONFIGDIR=/tmp/matplotlib
RUN mkdir -p /tmp/matplotlib


COPY . .
ENTRYPOINT ["python", "scripts/gpv_panel_daily_akita.py"]
