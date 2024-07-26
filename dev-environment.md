# Deploy hardware-observer with COS on real machine
This guide outlines the steps to deploy a development environment comprised of hardware-observer and COS on a single physical machine.

Most of hardware observer's functionality can only be experienced when installing the charm on server-grade hardware and relating to a COS installation. As this can be a relatively expensive setup, we are offering this guide to document how to create an environment for development or rapid prototyping on a single physical host. Note that the proposed topology is in no way appropriate for production, nor it can be considered a supported deployment.

If you have a physical machine that you can fully take over and expect to redeploy when you're done, you can follow these steps to set up the environment.


## Prerequisites
A physical machine. Here, "physical machine" refers to machines that are not VMs or containers and have access to real
hardware resources like RAID cards and BMC management tools.

A juju controller. You can find what is juju and how to deploy it [here](https://juju.is/docs/juju)


## Set up juju and lxd and deploy hardware-observer
First, you need to bootstrap a Juju controller on the machine. Using a default LXD controller should suffice.

### Extra requirements
Due to some [historical reasons](https://bugs.launchpad.net/juju/+bug/1964513), the machine hosting the LXD controller cannot be added to the model unless the default LXD bridge is renamed.
```
lxc network create br0 -t bridge
lxc profile edit default  # Rename lxdbr0 to br0 in the profile
lxc network delete lxdbr0
```

Bootstrap a LXD controller on juju:
```
juju bootstrap localhost lxd-controller
```

### Add physical machine
To add the physical machine to the model, you need to allow the juju client to log into it via SSH as a user with sudo rights. On an Ubuntu machine, the `ubuntu` user typically satisfies this requirement:
```
cat ~/.local/share/juju/ssh/juju_id_rsa.pub >> ~/.ssh/authorized_keys
```

Now you can create a model and add your physical machine via the manual provider:
```
juju add-model hw-obs
# use a different username if needed 
# any IP belonging to the host should work  
juju add-machine ssh:ubuntu@ip.add.re.ss
```

### Deploy Hardware-Observer
```
juju switch hw-obs
juju deploy ubuntu --to 0
juju deploy hardware-observer
juju deploy grafana-agent
```

Add necessary relations:
```
juju relate hardware-observer ubuntu
juju relate grafana-agent ubuntu
juju relate grafana-agent hardware-observer
```


## Set up microk8s and COS
### Set up microk8s
Install MicroK8s package, it is required to use a strictly confined version:
```
sudo snap install microk8s --channel 1.30-strict
```

Add your user to the `microk8s` group for unprivileged access:
```
sudo adduser $USER snap_microk8s
```

Give your user permissions to read the ~/.kube directory:
```
sudo chown -f -R $USER ~/.kube
```

Wait for MicroK8s to finish initialising:
```
sudo microk8s status --wait-ready
```

Enable the 'storage' and 'dns' addons:
```
sudo microk8s enable hostpath-storage dns
```

The COS bundle comes with Traefik to provide ingress, for which the metallb addon should be enabled:
```
# The IP address 2.2.2.2 is arbitrary and is used to determine the preferred source IP address for routing.
IPADDR=$(ip -4 -j route get 2.2.2.2 | jq -r '.[] | .prefsrc')
sudo microk8s enable metallb:$IPADDR-$IPADDR
```

Alias kubectl so it interacts with MicroK8s by default:
```
sudo snap alias microk8s.kubectl kubectl
```

Ensure your new group membership is apparent in the current terminal:
(Not required once you have logged out and back in again)
```
newgrp snap_microk8s
```

Juju recognises a local MicroK8s cloud automatically, bootstrap a microk8s controller:
```
juju bootstrap microk8s k8s-controller
```

### Integrate with COS
Before deploying the COS bundle, wait for all the microk8s addons to be rolled out:
```
microk8s kubectl rollout status deployments/hostpath-provisioner -n kube-system -w
microk8s kubectl rollout status deployments/coredns -n kube-system -w
microk8s kubectl rollout status daemonset.apps/speaker -n metallb-system -w
```

Create a COS model and deploy COS-lite bundle:
```
juju add-model cos
juju switch cos
curl -L https://raw.githubusercontent.com/canonical/cos-lite-bundle/main/overlays/offers-overlay.yaml -O
juju deploy cos-lite --trust --overlay ./offers-overlay.yaml
```

Switch back to your physical model and add the relations to COS:
```
juju switch hw-obs
juju relate grafana-agent k8s-controller:cos.prometheus-receive-remote-write
juju relate grafana-agent k8s-controller:cos.grafana-dashboards
juju relate grafana-agent k8s-controller:cos.loki-logging
```


## Check the dashboard
Go to COS model and run:
```
juju run grafana/0 get-admin-password
```

This command will show the grafana dashboard endpoint and default password.  The default username is "admin".
Now you should be able to access grafana.