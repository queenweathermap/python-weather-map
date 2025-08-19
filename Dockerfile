# ===============================================
# 共通 Dockerfile（Akita / JMA 兼用）
# - GRIB2 / Cartopy / pdf2image 対応
# - 日本語フォント（Noto CJK）/ JST / Matplotlib一時ディレクトリ
# - Cloud Run Jobs で --args によるスクリプト切替を前提
# ===============================================

FROM python:3.10-slim

# 必要ライブラリ（最小構成）
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

# ランタイム環境
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    MPLCONFIGDIR=/tmp/matplotlib \
    TZ=Asia/Tokyo
RUN mkdir -p /tmp/matplotlib

WORKDIR /app

# 依存インストール
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
# ※ GCS へアップロードする場合は、requirements.txt に `google-cloud-storage` を追加

# アプリ本体
COPY . .

# ここが共通化の要：ENTRYPOINT は python 固定
ENTRYPOINT ["python"]
# ローカル起動用の既定（Cloud Run Job では --args で上書き）
CMD ["scripts/gpv_panel_daily_akita.py"]
