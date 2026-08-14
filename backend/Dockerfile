FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# libgomp1 is the OpenMP runtime that the xgboost and scikit-learn wheels link
# against. Without it "import xgboost" fails and the API silently falls back to
# the linear surrogate instead of the trained ensemble.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# Demo laptops are often on slow or flaky connections, where pip's default 15s
# read timeout expires part-way through the large scientific wheels. The cache
# mount lives in the build cache rather than in an image layer, so a retry
# resumes from the wheels already fetched instead of re-downloading ~500 MB,
# and the image stays no bigger for it.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 120 --retries 10 -r requirements.txt

COPY . .

# The trained artefacts are gitignored, so an image built from a fresh clone
# would quietly serve surrogate scores. Fail the build instead, and pass
# --build-arg REQUIRE_MODEL=false to demo the UI without a trained model.
ARG REQUIRE_MODEL=true
RUN REQUIRE_MODEL="$REQUIRE_MODEL" python -c "import os, sys; \
from ml.features import artifacts_available, MODEL_PATH; \
present = artifacts_available(); \
print('Trained ensemble baked into image:', present, '->', MODEL_PATH); \
sys.exit(0 if present or os.environ['REQUIRE_MODEL'].lower() != 'true' else \
'ERROR: backend/ml artefacts missing. Run \"python -m ml.train_real_model\" in backend/ before building, or rebuild with --build-arg REQUIRE_MODEL=false.')"

# The database lives on a volume so demo data survives "docker compose down".
RUN useradd --create-home --uid 10001 foriflow \
    && mkdir -p /data \
    && chown -R foriflow:foriflow /app /data
USER foriflow

ENV FORIFLOW_DATABASE_URL=sqlite:////data/foriflow.db

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
