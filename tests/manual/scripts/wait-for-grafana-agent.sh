#!/bin/bash

MODEL="$("$TG_CTX_TF_PATH" output -raw model_name)"

juju switch $MODEL

juju wait-for application grafana-agent --query='name=="grafana-agent" && (status=="active" || status=="idle")'
