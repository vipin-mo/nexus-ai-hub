#!/usr/bin/env bash
# Create .env from .env.sample with random secrets.
#   scripts/generate_env.sh           create .env (refuses to overwrite)
#   scripts/generate_env.sh --merge   add keys missing from an existing .env; existing values are kept,
#                                     a timestamped backup is written first
set -euo pipefail
cd "$(dirname "$0")/.."

secret() { openssl rand -hex "${1:-24}"; }
value_for() {
  case "$1" in
    POSTGRES_PASSWORD|MONGO_PASSWORD) secret ;;
    NEXUS_INTERNAL_TOKEN) secret 32 ;;
    NEXUS_ADMIN_API_KEY) echo "nx_admin_$(secret 20)" ;;
    NEXUS_ANALYST_API_KEY) echo "nx_analyst_$(secret 20)" ;;
    NEXUS_INGEST_API_KEY) echo "nx_ingest_$(secret 20)" ;;
    *) grep -E "^$1=" .env.sample | head -1 | cut -d= -f2- ;;
  esac
}

if [[ "${1:-}" == "--merge" ]]; then
  [[ -f .env ]] || { echo "no .env to merge into; run without --merge" >&2; exit 1; }
  backup=".env.backup-$(date +%Y%m%d-%H%M%S)"
  cp -p .env "$backup"
  added=0
  while IFS= read -r line; do
    [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)= ]] || continue
    key="${BASH_REMATCH[1]}"
    if ! grep -qE "^${key}=" .env; then
      echo "${key}=$(value_for "$key")" >> .env
      echo "  added $key"
      added=$((added + 1))
    elif [[ -z "$(grep -E "^${key}=" .env | tail -1 | cut -d= -f2-)" ]]; then
      case "$key" in ANTHROPIC_API_KEY) continue ;; esac   # left empty on purpose until you add it
      sed -i.tmp -E "s|^${key}=$|${key}=$(value_for "$key")|" .env && rm -f .env.tmp
      echo "  filled empty $key"
      added=$((added + 1))
    fi
  done < .env.sample
  chmod 600 .env
  echo "merged $added key(s) into .env (backup: $backup). Existing values were not changed."
  exit 0
fi

if [[ -f .env ]]; then
  echo ".env already exists - use --merge to add missing keys." >&2
  exit 1
fi
while IFS= read -r line; do
  if [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)=$ && "${BASH_REMATCH[1]}" != "ANTHROPIC_API_KEY" ]]; then
    echo "${BASH_REMATCH[1]}=$(value_for "${BASH_REMATCH[1]}")"
  else
    echo "$line"
  fi
done < .env.sample > .env
chmod 600 .env
echo "Wrote .env with fresh random secrets (mode 600). Add ANTHROPIC_API_KEY yourself if you want Claude."
