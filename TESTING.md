# Deploy hardware-observer with COS on real machine
This guide outlines the steps to deploy the hardware-observer and COS on real hardware.

Here, "real hardware" refers to machines that are not VMs or containers and have access to real
hardware resources like RAID cards and BMC management tools.


## Set up juju and lxd and deploy hardware-observer
First, you need to bootstrap a Juju controller on the machine. Using a default LXD controller should suffice.

### Install Juju

Install Juju with the following command:
$ snap install juju

### Configure LXD

Due to some [historical reasons](https://bugs.launchpad.net/juju/+bug/1964513), the default bridge for LXD does not work,
if you try to add a local machine to the LXD controller. You will need to create a new bridge:
$ lxc network create br0 -t bridge
$ lxc profile edit default  # Rename lxdbr0 to br0 in the profile
$ lxc network delete lxdbr0

Then you can bootstrap an lxd controller:
$ juju bootstrap localhost hw-controller

To add local machine to the controller, you need to pass the juju client credential to it:
$ cat ~/.local/share/juju/ssh/juju_id_rsa.pub >> ~/.ssh/authorized_keys

Then you can manually add local machine, you can use the ip address that is linked to br0:
$ juju add-machine ssh:username@ip.add.re.ss

### Deploy Hardware-Observer
Create a new model and deploy hardware-observer along with the necessary agents:
$ juju add-model hw-obs
$ juju deploy ubuntu --to 0
$ juju deploy hardware-observer
$ juju deploy grafana-agent

Add necessary relations:
$ juju relate hardware-observer ubuntu
$ juju relate grafana-agent ubuntu
$ juju relate grafana-agent hardware-observer


## Set up microk8s and COS
The COS Lite bundle is a Juju-based observability stack, running on Kubernetes. The bundle consists of Prometheus, Loki, Alertmanager and Grafana.

### Set up microk8s

Install MicroK8s package:
$ sudo snap install microk8s --channel 1.30-strict

Add your user to the `microk8s` group for unprivileged access:
$ sudo adduser $USER snap_microk8s

Give your user permissions to read the ~/.kube directory:
$ sudo chown -f -R $USER ~/.kube

Wait for MicroK8s to finish initialising:
$ sudo microk8s status --wait-ready

Enable the 'storage' and 'dns' addons:
(required for the Juju controller)
$ sudo microk8s enable hostpath-storage dns

Alias kubectl so it interacts with MicroK8s by default:
$ sudo snap alias microk8s.kubectl kubectl

Ensure your new group membership is apparent in the current terminal:
(Not required once you have logged out and back in again)
$ newgrp snap_microk8s

The COS bundle comes with Traefik to provide ingress, for which the metallb addon should be enabled:
$ IPADDR=$(ip -4 -j route get 2.2.2.2 | jq -r '.[] | .prefsrc')
$ sudo microk8s enable metallb:$IPADDR-$IPADDR

Wait for all the addons to be rolled out
$ microk8s kubectl rollout status deployments/hostpath-provisioner -n kube-system -w
$ microk8s kubectl rollout status deployments/coredns -n kube-system -w
$ microk8s kubectl rollout status daemonset.apps/speaker -n metallb-system -w

### Deploy the COS Lite bundle with overlays
$ juju add-model cos
$ juju switch cos
$ curl -L https://raw.githubusercontent.com/canonical/cos-lite-bundle/main/overlays/offers-overlay.yaml -O
$ juju deploy cos-lite --trust --overlay ./offers-overlay.yaml

### Add cross-model relations
Go back to lxd controller and add cross-model relations
$ juju relate grafana-agent cos.prometheus-receive-remote-write
$ juju relate grafana-agent cos.grafana-dashboards
$ juju relate grafana-agent cos.loki-logging


## Check the dashboard
Go to COS model and run:
$ juju run grafana/0 get-admin-password

This command will show the dashboard endpoint and default password, the default uername is "admin".
Now you should be able to access the dashboard.