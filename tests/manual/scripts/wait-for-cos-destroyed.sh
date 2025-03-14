#!/bin/bash

MODEL="cos"

while juju show-model $MODEL > /dev/null ; do
    echo "$MODEL still exists.."
    sleep 5
done;
