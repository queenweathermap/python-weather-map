FROM ubuntu:22.04

# 必要パッケージ＋wgrib2
RUN apt-get update && \
    apt-get install -y python3 python3-pip wgrib2 wget git

WORKDIR /workspace

COPY . /workspace

RUN pip3 install --upgrade pip
RUN pip3 install -r requirements.txt

CMD ["python3", "scripts/main_weather_batch.py"]
