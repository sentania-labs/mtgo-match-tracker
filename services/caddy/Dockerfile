# Tamiyo — Caddy reverse proxy image.
# Pattern borrowed from ScarGuard: caddy:2-alpine + python3 for parsing
# env-driven TLS settings into a generated Caddyfile.
FROM caddy:2-alpine

RUN apk add --no-cache python3 py3-yaml

COPY services/caddy/entrypoint.sh /entrypoint.sh
COPY services/caddy/Caddyfile.template /etc/caddy/Caddyfile.template
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
