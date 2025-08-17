# ===============================================
# 秋田パネル用 Dockerfile（GRIB2直接処理/Slack通知対応）
# ===============================================

FROM python:3.11-slim

# Cartopy/cfgrib に必要なネイティブ依存
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential gfortran \
    proj-bin libproj-dev libgeos-dev \
    libeccodes0 libeccodes-dev \
    libnetcdf-dev libhdf5-dev \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 日本語フォントが必要なら有効化（任意）
# RUN apt-get update && apt-get install -y fonts-noto-cjk && rm -rf /var/lib/apt/lists/*

COPY . .
ENTRYPOINT ["python", "scripts/gpv_panel_daily_akita.py"]
