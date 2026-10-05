#!/bin/bash
# Start Cloudflare quick tunnel (fallback if DuckDNS goes down)
pkill -f "cloudflared tunnel --url" || true
sleep 2
LOG="/tmp/cloudflared.log"
rm -f $LOG
cloudflared tunnel --url http://localhost:80 > $LOG 2>&1 &
# Wait for URL to appear in log
for i in {1..30}; do
    URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' $LOG 2>/dev/null)
    if [ -n "$URL" ]; then
        break
    fi
    sleep 2
done
if [ -z "$URL" ]; then
    echo "Failed to get tunnel URL" >&2
    exit 1
fi
echo "Tunnel URL: $URL"
