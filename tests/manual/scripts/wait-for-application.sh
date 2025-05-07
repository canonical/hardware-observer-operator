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
    echo "Waiting for microk8s to be ready..."
    sudo microk8s status --wait-ready
fi
