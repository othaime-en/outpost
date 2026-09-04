#!/bin/bash
set -euxo pipefail

dnf update -y
dnf install -y docker git
systemctl enable --now docker

mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# AL2023's dnf-packaged docker ships an old buildx plugin (as of writing, 0.12.x)
# that's too old for `docker compose build`/`up --build` (requires >= 0.17.0).
# Replace it with a current release, same pattern as docker-compose above.
BUILDX_VERSION=$(curl -s https://api.github.com/repos/docker/buildx/releases/latest | grep '"tag_name"' | cut -d '"' -f4)
curl -SL "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64" \
  -o /usr/local/lib/docker/cli-plugins/docker-buildx
chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx

mkdir -p /opt/outpost