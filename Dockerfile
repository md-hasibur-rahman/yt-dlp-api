FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y ffmpeg curl nodejs npm && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# gunicorn instead of the Flask dev server; timeout is longer than the yt-dlp subprocess
# timeout so a slow extraction is not killed by the worker.
CMD ["sh", "-c", "gunicorn -w 1 --threads 4 -b 0.0.0.0:${PORT:-5000} --timeout 120 app:app"]
