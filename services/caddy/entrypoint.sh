#!/bin/sh
# Tamiyo — Caddy entrypoint.
#
# Reads TLS_MODE / TLS_DOMAIN from the environment, generates an active
# Caddyfile, and execs Caddy. The Caddyfile.template shipped in the image
# is reference only — the active config is produced here.
#
# TLS modes:
#   off     — HTTP only on :80 (dev/test)
#   manual  — HTTPS on :443 using /certs/cert.pem + /certs/key.pem
#   auto    — HTTPS on :443 via Let's Encrypt ACME (requires TLS_DOMAIN)
set -e

CADDYFILE="/etc/caddy/Caddyfile"

generate_caddyfile() {
    python3 - "$CADDYFILE" <<'PYEOF'
import os, sys, pathlib

caddyfile_path = sys.argv[1]

mode = os.environ.get("TLS_MODE", "off").strip().lower()
domain = os.environ.get("TLS_DOMAIN", "").strip()
cert_path = os.environ.get("TLS_CERT_PATH", "/certs/cert.pem")
key_path = os.environ.get("TLS_KEY_PATH", "/certs/key.pem")

# Shared snippet: reverse proxy to the FastAPI app + common hardening.
snippet = """(tamiyo) {
\theader {
\t\tX-Frame-Options DENY
\t\tX-Content-Type-Options nosniff
\t\tReferrer-Policy strict-origin-when-cross-origin
\t\t-Server
\t}
\treverse_proxy app:8000
}
"""

if mode == "auto":
    if not domain:
        print("[caddy-entrypoint] TLS_MODE=auto but TLS_DOMAIN is empty — falling back to HTTP", file=sys.stderr)
        body = f"{snippet}\n:80 {{\n\timport tamiyo\n}}\n"
    else:
        body = f"{snippet}\n{domain} {{\n\timport tamiyo\n}}\n"
elif mode == "manual":
    cert_ok = pathlib.Path(cert_path).exists()
    key_ok = pathlib.Path(key_path).exists()
    if cert_ok and key_ok:
        host = domain if domain else ":443"
        body = f"""{snippet}
{host} {{
\ttls {cert_path} {key_path}
\timport tamiyo
}}

:80 {{
\tredir https://{{host}}{{uri}} permanent
}}
"""
    else:
        missing = []
        if not cert_ok:
            missing.append(f"cert ({cert_path})")
        if not key_ok:
            missing.append(f"key ({key_path})")
        print(f"[caddy-entrypoint] TLS_MODE=manual but missing: {', '.join(missing)} — falling back to HTTP", file=sys.stderr)
        body = f"{snippet}\n:80 {{\n\timport tamiyo\n}}\n"
else:
    if mode not in ("off", ""):
        print(f"[caddy-entrypoint] Unknown TLS_MODE '{mode}' — defaulting to HTTP", file=sys.stderr)
    body = f"{snippet}\n:80 {{\n\timport tamiyo\n}}\n"

pathlib.Path(caddyfile_path).write_text(body)
print(f"[caddy-entrypoint] Generated Caddyfile (mode={mode})", file=sys.stderr)
PYEOF
}

generate_caddyfile
exec caddy run --config "$CADDYFILE" --adapter caddyfile
