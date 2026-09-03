#!/usr/bin/env bash
set -euo pipefail
: "${IMAGE_DIGEST:?required}"
install -d -m 0700 /opt/oh-lyme /root/.docker
install -m 0600 /tmp/pmc-runtime.env /opt/oh-lyme/pmc-runtime.env
install -m 0600 /tmp/docker-config.json /root/.docker/config.json
cat >/etc/systemd/system/oh-lyme-pmc-extraction.service <<EOF
[Unit]
Description=Bounded approved PMC extraction
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
EnvironmentFile=/opt/oh-lyme/pmc-runtime.env
ExecStart=/usr/bin/docker run --rm --env-file /opt/oh-lyme/pmc-runtime.env registry.digitalocean.com/oh-lyme-data/pipeline@${IMAGE_DIGEST} /app/.venv/bin/atlas-data pipeline pmc-extract --estimated-cost-usd 0.10 --confirm
EOF
cat >/etc/systemd/system/oh-lyme-pmc-extraction.timer <<'EOF'
[Unit]
Description=Weekly bounded PMC extraction
[Timer]
OnCalendar=Mon *-*-* 08:45:00 America/Denver
Persistent=true
[Install]
WantedBy=timers.target
EOF
rm -f /tmp/pmc-runtime.env /tmp/docker-config.json
systemctl daemon-reload
systemctl enable --now oh-lyme-pmc-extraction.timer
