#!/bin/bash

set -xe

# Clean up all resources idempotently

juju destroy-model hw-obs --no-prompt --force --no-wait || true
juju destroy-model cos --no-prompt --force --no-wait || true
juju remove-cloud --client --controller $(juju controllers --format json | jq '{.current-controller}') || true
sudo /sbin/remove-juju-services || true
