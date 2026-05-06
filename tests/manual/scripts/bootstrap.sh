#!/bin/bash

set -xe

sudo apt update

# Set up packages
sudo snap install juju
sudo snap install terraform --classic
sudo snap install charmcraft --classic
sudo apt-get install tox jq ubuntu-drivers-common -y

# Download terragrunt
if [ ! -e /usr/local/bin/terragrunt ]; then
    OS="linux"
    ARCH="amd64"
    VERSION="v0.69.10"
    BINARY_NAME="terragrunt_${OS}_${ARCH}"
    sudo curl -sL "https://github.com/gruntwork-io/terragrunt/releases/download/$VERSION/$BINARY_NAME" -o "/usr/local/bin/terragrunt"
    sudo chmod +x /usr/local/bin/terragrunt
else
    echo "terragrunt already installed"
fi

# Install nvidia package
sudo ubuntu-drivers --gpgpu install
if ! sudo modprobe nvidia; then
    echo "Failed to add nvidia kernel module"
fi

USER=$(whoami)
UBUNTU_MAJOR=$(lsb_release -sr | cut -d. -f1)

if [ "$UBUNTU_MAJOR" -lt 24 ]; then
    # Workaround for https://bugs.launchpad.net/juju/+bug/1964513 (pre-Noble issue)
    BRIDGE="br0"
    if [ -z "$(sudo --user $USER lxc storage list --format csv)" ]; then
        echo 'Bootstrapping LXD'
        cat <<EOF | sudo --user $USER lxd init --preseed
networks:
- config:
    ipv4.address: auto
    ipv6.address: none
  name: $BRIDGE
  project: default
storage_pools:
- name: default
  driver: dir
profiles:
- devices:
    eth0:
      name: eth0
      network: $BRIDGE
      type: nic
    root:
      path: /
      pool: default
      type: disk
  name: default
EOF
    fi
else
    BRIDGE="lxdbr0"
    if ! ip link show "$BRIDGE" > /dev/null 2>&1; then
        echo 'Bootstrapping LXD'
        sudo --user $USER lxd init --auto
    fi
fi

BRIDGE_ADDR=$(ip -4 -j a sho dev $BRIDGE | jq -r .[].addr_info[0].local)
if [ -z "$BRIDGE_ADDR" ]; then
    echo "Failed to configure LXD with bridge $BRIDGE"
    exit 1
fi

# Generate SSH key and add of known ips to known hosts
[ -f $HOME/.ssh/id_rsa ] || ssh-keygen -b 4096 -f $HOME/.ssh/id_rsa -t rsa -N ""
cat $HOME/.ssh/id_rsa.pub >> $HOME/.ssh/authorized_keys
ssh-keyscan -H $(hostname --all-ip-addresses) >> $HOME/.ssh/known_hosts

# Bootstrap juju controller
juju bootstrap localhost lxd-controller
