FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY missing_patch_detector ./missing_patch_detector

RUN pip install --upgrade pip \
    && pip install .

RUN useradd -m appuser \
    && mkdir -p /data/repos /data/reports \
    && chown -R appuser:appuser /data/repos /data/reports

USER appuser

# Runtime volumes (mounted by docker-compose)
VOLUME ["/data/repos", "/data/reports"]

CMD ["python", "-c", "print('Missing Patch Detector image is ready. Override command to run scans.')"]
