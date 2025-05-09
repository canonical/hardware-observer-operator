#!/bin/bash
set -euo pipefail
set -x

APPLICATION="$1"

TIMEOUT=300
DELAY=5
START=$(date +%s)

while true; do
  if microk8s kubectl version --request-timeout=5s >/dev/null 2>&1; then
    echo "✅ Kubernetes API is ready"
    break
  fi

  NOW=$(date +%s)
  if (( NOW - START > TIMEOUT )); then
    echo "❌ Timed out waiting for Kubernetes API"
    exit 1
  fi

  echo "⏳ Waiting for Kubernetes API..."
  sleep "$DELAY"
done
