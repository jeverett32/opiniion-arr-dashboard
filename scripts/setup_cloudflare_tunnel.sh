#!/usr/bin/env bash
# Run AFTER `cloudflared tunnel login` succeeds (cert in ~/.cloudflared/cert.pem).
set -euo pipefail

TUNNEL_NAME="${TUNNEL_NAME:-arr-dashboard}"
HOSTNAME="${HOSTNAME_DNS:-}"  # e.g. arr.example.com — required for DNS route
SERVICE_URL="${SERVICE_URL:-http://127.0.0.1:8000}"

if [[ ! -f "$HOME/.cloudflared/cert.pem" ]]; then
  echo "Missing ~/.cloudflared/cert.pem — run: cloudflared tunnel login"
  exit 1
fi

if ! cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
  echo "Creating tunnel: $TUNNEL_NAME"
  cloudflared tunnel create "$TUNNEL_NAME"
else
  echo "Tunnel already exists: $TUNNEL_NAME"
fi

TUNNEL_ID=$(cloudflared tunnel list | awk -v n="$TUNNEL_NAME" '$2==n {print $1; exit}')
CRED="$HOME/.cloudflared/${TUNNEL_ID}.json"
CONFIG="$HOME/.cloudflared/config.yml"

cat > "$CONFIG" <<EOF
tunnel: $TUNNEL_ID
credentials-file: $CRED

ingress:
  - hostname: ${HOSTNAME:-arr.localhost}
    service: $SERVICE_URL
  - service: http_status:404
EOF

echo "Wrote $CONFIG"
echo "Tunnel ID: $TUNNEL_ID"

if [[ -n "$HOSTNAME" ]]; then
  echo "Routing DNS $HOSTNAME -> $TUNNEL_NAME"
  cloudflared tunnel route dns "$TUNNEL_NAME" "$HOSTNAME"
else
  echo "Skip DNS route (set HOSTNAME_DNS=arr.yourdomain.com to create it)."
fi

echo
echo "Install & start system service:"
echo "  sudo cloudflared service install"
echo "  sudo systemctl enable --now cloudflared"
echo
echo "Or run foreground:"
echo "  cloudflared tunnel run $TUNNEL_NAME"
