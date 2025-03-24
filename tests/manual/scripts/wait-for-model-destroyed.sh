#!/bin/bash

MODEL="$1"

if [ -z "$MODEL" ]; then
    echo "Wait for the model to be destroyed."
    echo ""
    echo "Usage: $0 <MODEL>"
    exit 1
fi

while juju show-model $MODEL > /dev/null ; do
    echo "$MODEL still exists.."
    sleep 5
done;
