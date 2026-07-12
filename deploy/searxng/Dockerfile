# SearXNG metasearch for NexusReach — deployed as its own private service
# (Railway, Fly, a VPS, ...). Nothing in the app bundles SearXNG; the backend
# only calls its JSON API over the private network. Build context is THIS
# directory (deploy/searxng), so `COPY settings.yml` resolves locally.
#
# Pinned 2026-07-11 image and multi-architecture digest.
FROM searxng/searxng:2026.7.11-62a1ab7ed@sha256:aaf56bb5ad737d48a8a375778d42eb4ab1757231e6b1eb7980e71d8dd5bdf0de

# Bake our production settings (JSON API enabled, limiter, timeouts) into the
# image so no runtime volume mount is required on platforms like Railway.
COPY --chown=977:977 settings.yml /etc/searxng/settings.yml

# The official image serves on 8080. Set SEARXNG_SECRET (a long random string)
# as a service env var; the entrypoint substitutes it into the settings'
# `ultrasecretkey` placeholder at boot.
EXPOSE 8080

USER 977:977
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["/usr/local/searxng/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
