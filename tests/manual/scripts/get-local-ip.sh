#!/bin/bash

UBUNTU_MAJOR=$(lsb_release -sr | cut -d. -f1)
if [ "$UBUNTU_MAJOR" -lt 24 ]; then
    # br0 bridges the physical NIC so its IP equals the external IP
    ip -4 -j a sho dev br0 | jq -r .[].addr_info[0].local
else
    # On Noble+, lxdbr0 is NAT-only so its gateway IP doesn't match the machine's real IP;
    # Here use the routing-preferred source address instead
    ip -4 -j route get 2.2.2.2 | jq -r '.[] | .prefsrc'
fi
