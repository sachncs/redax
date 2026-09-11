FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Install the exact pinned + hashed dependency set the project tests against.
# Pinned-only: range specifiers are banned. This is the same lockfile used
# by `make install` locally, so the production image and dev environment
# are bit-for-bit reproducible.
COPY requirements.lock /build/requirements.lock
RUN pip install --prefix=/install --no-deps -r /build/requirements.lock

# Install the package itself with no deps (deps were resolved above).
COPY pyproject.toml /build/
COPY app /build/app
RUN pip install --prefix=/install --no-deps /build

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REDAX_MODEL_CACHE=/models \
    REDAX_AUDIT_PATH=/var/lib/redax/audit.jsonl \
    REDAX_POLICIES_DIR=/policies

RUN groupadd -r redax && useradd -r -g redax -d /app -s /sbin/nologin redax \
    && mkdir -p /app /models /var/lib/redax /policies \
    && chown -R redax:redax /app /models /var/lib/redax /policies

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app /app/app
COPY policies /policies

# Pin and SHA-256-verify the production detector snapshot. Fail loud
# (non-zero exit, container refuses to start) if the local copy does
# not match the committed digest. Regenerate with:
#   python scripts/download_models.py \
#       --model OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1 \
#       --revision df7af994d39d358e52f929ff1b3a40d894adf022 --record
COPY MODEL_HASHES.txt MODEL_HASHES.txt
COPY scripts/download_models.py scripts/download_models.py
# Models are downloaded as root here so the cache directory created
# above can be chowned to the `redax` user before USER redax is set.
# The produced files live under /models which is already owned by
# redax:redax (see the mkdir/chown above); the build step itself runs
# as root for one RUN instruction only.
RUN python scripts/download_models.py \
        --model OpenMed/OpenMed-PII-SuperClinical-Large-434M-v1 \
        --revision df7af994d39d358e52f929ff1b3a40d894adf022

USER redax

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import httpx; httpx.get('http://localhost:8000/healthz', timeout=2).raise_for_status()"]

CMD ["python", "-m", "app.main"]
