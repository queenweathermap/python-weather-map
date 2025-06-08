FROM ubuntu:22.04

# 基本ツール
RUN apt-get update && \
    apt-get install -y \
        wget git bzip2 \
        python3 python3-pip \
        build-essential python3-dev libfreetype6-dev pkg-config

# Miniconda導入・wgrib2インストール（先ほどのままでOK）
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-py311_24.1.2-0-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh && \
    /opt/conda/bin/conda clean -tipsy && \
    ln -s /opt/conda/etc/profile.d/conda.sh /etc/profile.d/conda.sh && \
    echo ". /opt/conda/etc/profile.d/conda.sh" >> ~/.bashrc && \
    echo "conda activate base" >> ~/.bashrc

ENV PATH="/opt/conda/bin:$PATH"

# wgrib2をconda-forgeからインストール
RUN conda install -c conda-forge wgrib2

WORKDIR /workspace

COPY . /workspace

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

CMD ["python3", "scripts/main_weather_batch.py"]
