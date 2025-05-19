#!/bin/bash
set -euo pipefail

APPLICATION="$1"

TIMEOUT=300
DELAY=5
START=$(date +%s)

while true; do
  if sudo microk8s kubectl create clusterrole test --verb=get --resource=pods --request-timeout=5s >/dev/null 2>&1; then
    echo "✅ Kubernetes API is ready"
    sudo microk8s kubectl delete clusterrole test --ignore-not-found >/dev/null 2>&1
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
