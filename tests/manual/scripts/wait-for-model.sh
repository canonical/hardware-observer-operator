#!/bin/bash

MODEL="$1"

if [ -z "$MODEL" ]; then
    echo "Wait for all applications in the model reaches active and idle."
    echo ""
    echo "Usage: $0 <MODEL>"
    exit 1
fi

juju wait-for model $MODEL --timeout=20m0s --query='forEach(applications, app => app.status == "active")'
