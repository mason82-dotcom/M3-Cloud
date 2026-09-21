FROM --platform=linux/amd64 python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN python -m pip install --no-cache-dir .

ENV DJI_TSDK_DIR=/opt/dji-tsdk

ENTRYPOINT ["m3-thermal-worker"]
