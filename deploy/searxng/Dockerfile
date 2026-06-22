# SearXNG metasearch for NexusReach — deployed as its own private service
# (Railway, Fly, a VPS, ...). Nothing in the app bundles SearXNG; the backend
# only calls its JSON API over the private network. Build context is THIS
# directory (deploy/searxng), so `COPY settings.yml` resolves locally.
#
# Pin to a dated tag for reproducible deploys (see https://hub.docker.com/r/searxng/searxng/tags).
# `latest` is used here for convenience — pin it before going to production.
FROM searxng/searxng:latest

# Bake our production settings (JSON API enabled, limiter, timeouts) into the
# image so no runtime volume mount is required on platforms like Railway.
COPY settings.yml /etc/searxng/settings.yml

# The official image serves on 8080. Set SEARXNG_SECRET (a long random string)
# as a service env var; the entrypoint substitutes it into the settings'
# `ultrasecretkey` placeholder at boot.
EXPOSE 8080
