FROM python:3.12-slim

# DejaVu has the accented letters the charts need ("Dólar", "días"); slim images ship no fonts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# Token, alerts and settings live in /data, mounted from the host, never inside the image.
ENV DOLAR_CHE_HOME=/data \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]

RUN useradd --create-home --uid 1000 dolarche && mkdir -p /data && chown dolarche /data
USER dolarche

CMD ["dolar-che"]
