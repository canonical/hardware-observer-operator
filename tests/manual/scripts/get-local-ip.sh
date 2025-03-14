#!/bin/bash

ip -4 -j a sho dev br0 | jq -r .[].addr_info[0].local
