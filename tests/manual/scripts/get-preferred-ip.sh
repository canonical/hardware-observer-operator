#!/bin/bash

echo "$(ip -4 -j route get 2.2.2.2 | jq -r '.[] | .prefsrc')-$(ip -4 -j route get 2.2.2.2 | jq -r '.[] | .prefsrc')"
