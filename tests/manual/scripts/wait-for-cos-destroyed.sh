#!/bin/bash

MODEL="$("$TG_CTX_TF_PATH" output -raw model_name)"

while juju show-model $MODEL > /dev/null ; do
    echo "$MODEL still exists.."
    sleep 5
done;
