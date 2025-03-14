#!/bin/bash

MODEL="$("$TG_CTX_TF_PATH" output -raw model_name)"

juju switch $MODEL

juju wait-for application alertmanager --query='name=="alertmanager" && (status=="active" || status=="idle")'
juju wait-for application catalogue --query='name=="catalogue" && (status=="active" || status=="idle")'
juju wait-for application grafana --query='name=="grafana" && (status=="active" || status=="idle")'
juju wait-for application loki --query='name=="loki" && (status=="active" || status=="idle")'
juju wait-for application metallb --query='name=="metallb" && (status=="active" || status=="idle")'
juju wait-for application prometheus --query='name=="prometheus" && (status=="active" || status=="idle")'
juju wait-for application traefik --query='name=="traefik" && (status=="active" || status=="idle")'
