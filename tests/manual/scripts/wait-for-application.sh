#!/bin/bash

MODEL="$1"
APPLICATION="$2"

if [ -z "$APPLICATION" ]; then
    echo "Wait for an juju application to reach active and idle."
    echo ""
    echo "Usage: $0 <MODEL> <APPLICATION>"
    exit 1
fi

juju switch $MODEL

juju wait-for application $APPLICATION --query='status=="active" || status=="idle"'

if [[ "$APPLICATION" == "microk8s" ]]; then
    echo "Waiting for API server to respond..."
    for i in {1..20}; do
        if curl --insecure --silent https://127.0.0.1:16443/healthz | grep -q "401"; then
            echo "API server is up and running."
            break
        else
            echo "API server not ready yet, retrying..."
            sleep 3
        fi
    done

fi
