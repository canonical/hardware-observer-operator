#!/bin/bash
set -euo pipefail
set -x

MODEL="$1"
APPLICATION="$2"

bash ./wait-for-application.sh "hw-obs" "microk8s"


API="https://127.0.0.1:16443"
KUBECONFIG="/var/snap/microk8s/current/credentials/client.config"
TIMEOUT=300
DELAY=5
START=$(date +%s)

while true; do
  if microk8s kubectl --kubeconfig="$KUBECONFIG" version --request-timeout=5s >/dev/null 2>&1; then
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
