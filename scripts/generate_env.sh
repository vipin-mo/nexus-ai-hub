#!/usr/bin/env bash
# Create .env from .env.sample with random secrets. Refuses to overwrite an existing .env.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  echo ".env already exists - not overwriting. Delete it first to regenerate." >&2
  exit 1
fi

secret() { openssl rand -hex "${1:-24}"; }

sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(secret)|" \
    -e "s|^MONGO_PASSWORD=.*|MONGO_PASSWORD=$(secret)|" \
    -e "s|^NEXUS_INTERNAL_TOKEN=.*|NEXUS_INTERNAL_TOKEN=$(secret 32)|" \
    -e "s|^NEXUS_ADMIN_API_KEY=.*|NEXUS_ADMIN_API_KEY=nx_admin_$(secret 20)|" \
    -e "s|^NEXUS_ANALYST_API_KEY=.*|NEXUS_ANALYST_API_KEY=nx_analyst_$(secret 20)|" \
    -e "s|^NEXUS_INGEST_API_KEY=.*|NEXUS_INGEST_API_KEY=nx_ingest_$(secret 20)|" \
    .env.sample > .env
chmod 600 .env
echo "Wrote .env with fresh random secrets (mode 600). Add ANTHROPIC_API_KEY yourself if you want Claude."
