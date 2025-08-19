# ===============================================
# 共通 Dockerfile（Akita/JMA 兼用）
#  - GRIB2 直接処理 / pdf2image / Cartopy など対応
#  - 文字化け防止の日本語フォント & JST
# ===============================================

FROM python:3.10-slim

# 必要ライブラリ
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential gfortran \
    proj-bin libproj-dev libgeos-dev \
    libeccodes0 libeccodes-dev \
    libnetcdf-dev libhdf5-dev \
    poppler-utils \
    tzdata \
    fonts-noto-cjk \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    MPLCONFIGDIR=/tmp/matplotlib \
    TZ=Asia/Tokyo
RUN mkdir -p /tmp/matplotlib

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# ※ GCS へ上げるなら requirements.txt に google-cloud-storage を追記

COPY . .

# 共通化のキモ：ここは python 固定。実行スクリプトは Job 側の --args で渡す
ENTRYPOINT ["python"]
# 手元実行のデフォルト（Cloud Run Job では --args で上書き）
CMD ["scripts/gpv_panel_daily_akita.py"]
