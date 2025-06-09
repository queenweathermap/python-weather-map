FROM ubuntu:22.04

# 基本ツール
RUN apt-get update && \
    apt-get install -y \
      wget git bzip2 \
      python3 python3-pip \
      build-essential python3-dev libfreetype6-dev pkg-config \
      libcrypt1
     apt-get update && apt-get install -y fonts-ipaex-gothic


# Miniconda導入・wgrib2インストール（先ほどのままでOK）
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
RUN bash /tmp/miniconda.sh -b -p /opt/conda
RUN rm /tmp/miniconda.sh
RUN /opt/conda/bin/conda clean -a -y
# RUN /opt/conda/bin/conda clean -tipsy  ← 削除やコメントアウトでもOK
RUN ln -s /opt/conda/etc/profile.d/conda.sh /etc/profile.d/conda.sh
RUN echo ". /opt/conda/etc/profile.d/conda.sh" >> ~/.bashrc
RUN echo "conda activate base" >> ~/.bashrc


ENV PATH="/opt/conda/bin:$PATH"
ENV PYTHONPATH=/workspace

# wgrib2をconda-forgeからインストール
RUN conda install -c conda-forge wgrib2

WORKDIR /workspace

COPY . /workspace

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

CMD ["python3", "scripts/main_weather_batch.py"]
