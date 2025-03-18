#!/bin/bash

set -e

JOB="$1"
SERIES="$2"
SSH_IMPORT_ID="$3"

if [ ! -d "$JOB" ] || [ -z "$SERIES" ] || [ -z "$SSH_IMPORT_ID" ]; then
  echo "Usage: $0 <JOB> <SERIES> <SSH_IMPORT_ID>"
  exit 1
fi

# testflinger cannot access /tmp file because it does not have necessary permission
TEMPFILE="./.tmp-job.yaml"
touch $TEMPFILE

sed -e "s/<SERIES>/$SERIES/g" -e "s/<SSH_IMPORT_ID>/$SSH_IMPORT_ID/g" "$JOB/job.tpl.yaml" | tee "$TEMPFILE"

testflinger submit $TEMPFILE

rm -f $TEMPFILE
