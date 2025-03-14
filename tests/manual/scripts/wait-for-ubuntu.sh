#!/bin/bash

MODEL="$("$TG_CTX_TF_PATH" output -raw model_name)"

juju switch $MODEL

juju wait-for application ubuntu --query='name=="ubuntu" && (status=="active" || status=="idle")'
