# smiles2iupac container image. Builds locally; intended for HF Spaces (which
# auto-detects a root Dockerfile) and Render once a deployment is wired up.
# No public deployment exists yet — see deploy/README.md for setup steps.
# Local test: `docker build -t s2i . && docker run -p 7860:7860 s2i`.
#
# Python 3.10 is intentional: STOUT-pypi 2.0.5 pins tensorflow==2.10.1, and
# TF 2.10 only publishes wheels for Python 3.7-3.10 (Python 3.11 support landed
# in TF 2.12). 3.11-slim looked plausible but pip can't resolve the TF dep there.
# Once STOUT-pypi releases an unpinned/newer-TF version, this can move forward.
#
# slim is glibc-based; RDKit, TensorFlow, and gradio all ship manylinux2014 wheels
# that need glibc — alpine (musl) would force source builds.
FROM python:3.10-slim

# OPSIN is a Java library; py2opsin shells out to a JVM. default-jre-headless
# tracks whatever Debian release the base image is on (bookworm: openjdk-17,
# trixie: openjdk-21). OPSIN runs on Java 8+, so any current JRE works.
# Pinning a specific major version breaks when python:3.10-slim updates its
# Debian base.
# curl is for the HEALTHCHECK below; ca-certificates lets pip/PubChem reach HTTPS.
# libxrender1 + libxext6 are X11 libs that RDKit's rdMolDraw2D links against
# (even for headless PNG/SVG rendering); python:slim strips them out.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        default-jre-headless \
        curl \
        ca-certificates \
        libxrender1 \
        libxext6 \
        libexpat1 \
        libfreetype6 \
        libfontconfig1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# HF Spaces and most container hosts run as a non-root user. Pre-create one
# so STOUT's model cache (~/.STOUT) lives under a writable home.
RUN useradd --create-home --shell /bin/bash --uid 1000 app

# Dep layer first — only changes when pyproject.toml changes. Copy src/ here too
# because hatchling needs the package tree present to do an editable install.
COPY --chown=app:app pyproject.toml README.md LICENSE /app/
COPY --chown=app:app src/ /app/src/

# Upgrade pip; install [ml] (py2opsin/OPSIN) + [web] (gradio, fastapi, uvicorn).
# STOUT generation is intentionally NOT installed — upstream weights URL is 404
# as of 2026-05-03 (see pyproject [stout] extra comment). Pipeline falls back
# cleanly to PubChem+OPSIN. dev extras excluded; no pytest in prod.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e .[ml,web]

USER app

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
