FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y ffmpeg curl unzip && \
    rm -rf /var/lib/apt/lists/*

# yt-dlp's EJS challenge solver requires Deno >= 2.3 on PATH; the Debian nodejs package
# is far too old to qualify. Versionless URL pulls the latest stable at build time —
# rebuild the service to pick up newer releases (same policy as requirements.txt).
RUN curl -fsSL https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip && \
    unzip /tmp/deno.zip -d /usr/local/bin && \
    chmod +x /usr/local/bin/deno && \
    rm /tmp/deno.zip && \
    deno --version

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# gunicorn instead of the Flask dev server; timeout is longer than the yt-dlp subprocess
# timeout so a slow extraction is not killed by the worker.
CMD ["sh", "-c", "gunicorn -w 1 --threads 4 -b 0.0.0.0:${PORT:-5000} --timeout 120 app:app"]
