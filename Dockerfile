# Dockerfile
# ===============================================
# python-weather-map用 Dockerfile
# ・日本語フォント, wgrib2, Miniconda, pipパッケージ一式
# ・RUN時にmain_weather_batch.pyを実行
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

# ---- Miniconda導入＆wgrib2（conda-forge） ----
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

# --- デフォルトコマンド（バッチ実行） ---
CMD ["python3", "main_weather_batch.py"]
