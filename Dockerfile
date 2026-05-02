# smiles2iupac production image — used by HF Spaces (root Dockerfile auto-detected)
# and Render. Local: `docker build -t s2i . && docker run -p 7860:7860 s2i`.
#
# Python 3.11 is intentional: STOUT-pypi 2.0.5 pins tensorflow==2.10.1 which has
# no Python 3.12 wheels. Bumping past 3.11 here breaks the [ml] install. Once
# STOUT-pypi releases an unpinned/newer-TF version, this can move to 3.12-slim.
#
# slim is glibc-based; RDKit, TensorFlow, and gradio all ship manylinux2014 wheels
# that need glibc — alpine (musl) would force source builds.
FROM python:3.11-slim

# OPSIN is a Java library; py2opsin shells out to a JVM. headless JRE keeps
# the layer small (no X11/AWT). 17 is the current Debian-stable LTS.
# curl is for the HEALTHCHECK below; ca-certificates lets pip/PubChem reach HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        curl \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# HF Spaces and most container hosts run as a non-root user. Pre-create one
# so STOUT's model cache (~/.STOUT) lives under a writable home.
RUN useradd --create-home --shell /bin/bash --uid 1000 app

# Dep layer first — only changes when pyproject.toml changes. Copy src/ here too
# because hatchling needs the package tree present to do an editable install.
COPY --chown=app:app pyproject.toml README.md LICENSE /app/
COPY --chown=app:app src/ /app/src/

# Upgrade pip to get the resolver fixes; install ml + web extras (TensorFlow,
# STOUT, gradio, fastapi). dev extras are intentionally excluded — no pytest in prod.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e .[ml,web]

USER app

# Bake STOUT model weights into the image. First call pulls ~500MB from the
# Steinbeck group's release; baking them avoids a multi-minute cold start on
# every container boot (HF Spaces sleeps idle Spaces and rebuilds frequently).
# If this layer fails, comment out and document; weights will lazy-download instead.
RUN python -c "from STOUT import translate_forward; translate_forward('CCO')"

# App code last — most-frequently-changed layer, so it sits on top of the stable
# dependency + model layers. Edits to app/ rebuild only this layer (~seconds).
COPY --chown=app:app app/ /app/app/

# HF Spaces hard-codes 7860; Render reads $PORT but defaults to 7860 fine.
EXPOSE 7860

# Container-level liveness probe. /health is exposed by app.gradio_app's FastAPI
# mount (parallel agent's contract). 30s interval, 5s timeout, 3 retries before unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:7860/health || exit 1

CMD ["python", "-m", "app.gradio_app"]
