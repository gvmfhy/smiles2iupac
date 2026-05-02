# Deploy

The production `Dockerfile` lives at the repo root (`../Dockerfile`) so Hugging
Face Spaces auto-detects it. This directory holds deployment notes only.

## Local Docker

```bash
docker build -t s2i .
docker run -p 7860:7860 s2i
# open http://localhost:7860
```

The image bakes STOUT model weights at build time (~500 MB, ~3-5 min). Subsequent
runs start in seconds. `/health` is wired for orchestrator probes.

## Hugging Face Spaces (primary)

Free tier, 16 GB RAM CPU Space. Auto-redeploys on push to `main` via
`.github/workflows/deploy-hf.yml`.

**One-time setup:**

1. Create the Space at <https://huggingface.co/new-space> as `gvmfhy/smiles2iupac`,
   SDK = **Docker**, hardware = CPU basic (free).
2. In the GitHub repo, add secret `HF_TOKEN` (Settings → Secrets and variables →
   Actions). Generate the token at <https://huggingface.co/settings/tokens> with
   **write** scope.
3. Push to `main`. The workflow force-pushes the GitHub repo to the Space.

HF Spaces detects the root `Dockerfile` automatically — no extra config needed.
The Space URL will be `https://gvmfhy-smiles2iupac.hf.space`.

## Render (CPU-only fallback)

1. New → Web Service → connect this repo.
2. Runtime: **Docker**. Dockerfile path: `./Dockerfile` (default). Docker context: `.`.
3. Plan: Standard ($7/mo) or higher — Free tier (512 MB) is too small for TensorFlow.
4. Health check path: `/health`. Auto-deploy on push to `main`.

Render reads `$PORT` (defaults to 10000); the app honors it. No env vars required.

## Environment variables

None today. The pipeline is stateless; cache is an in-image SQLite file under
`~/.smiles2iupac/`. If you want the cache to survive redeploys, mount a persistent
volume at `/home/app/.smiles2iupac/`.

## Healthcheck monitoring

`.github/workflows/healthcheck.yml` pings the HF Spaces `/health` endpoint every
10 minutes. Failures show up in the Actions tab — a free uptime monitor.

## Troubleshooting

- **STOUT bake step fails during build:** the `RUN python -c "from STOUT ..."`
  line in the Dockerfile downloads weights. If your network blocks the
  Steinbeck CDN, comment it out — weights will lazy-download on first request.
- **HF Space stuck "Building":** check the Space's build logs. Most often a
  TensorFlow wheel mismatch — pin in `pyproject.toml` if needed.
- **OPSIN crashes with `JavaError`:** the `openjdk-17-jre-headless` package didn't
  install. Verify with `docker run s2i java -version`.
