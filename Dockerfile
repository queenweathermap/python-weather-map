# Dockerfile
# ===============================================
# python-weather-map用 Dockerfile（Slack通知専用）
# ・wgrib2, 日本語フォント, Miniconda, pipパッケージ
# ・main_weather_batch.py実行
# 2025-06-16 by ChatGPT
# ===============================================

FROM ubuntu:22.04

# ---- 基本ツール・日本語フォント ----
RUN apt-get update && \
    apt-get install -y \
      wget git bzip2 \
      python3 python3-pip \
      build-essential python3-dev libfreetype6-dev pkg-config \
      libcrypt1 \
      fonts-ipafont-gothic


RUN apt-get update && apt-get install -y fonts-ipafont-gothic


# ---- Miniconda導入＆wgrib2 ----
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
RUN bash /tmp/miniconda.sh -b -p /opt/conda
RUN rm /tmp/miniconda.sh
RUN /opt/conda/bin/conda clean -a -y
RUN ln -s /opt/conda/etc/profile.d/conda.sh /etc/profile.d/conda.sh
RUN echo ". /opt/conda/etc/profile.d/conda.sh" >> ~/.bashrc
RUN echo "conda activate base" >> ~/.bashrc

ENV PATH="/opt/conda/bin:$PATH"
ENV PYTHONPATH=/workspace

RUN conda install -c conda-forge wgrib2

WORKDIR /workspace

COPY . /workspace

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# --- デフォルトコマンド（Slackバッチ） ---
CMD ["python3", "main_weather_batch.py"]
