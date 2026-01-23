# Deploy hardware-observer with COS on real machine
This guide outlines the steps to deploy a development environment comprised of hardware-observer and COS on a single physical machine.

Most of hardware observer's functionality can only be experienced when installing the charm on server-grade hardware and relating to a COS installation. As this can be a relatively expensive setup, we are offering this guide to document how to create an environment for development or rapid prototyping on a single physical host. Note that the proposed topology is in no way appropriate for production, nor it can be considered a supported deployment.

If you have a physical machine that you can fully take over and expect to redeploy when you're done, you can follow these steps to set up the environment.


## Prerequisites
A physical machine. Here, "physical machine" refers to machines that are not VMs or containers and have access to real
hardware resources like RAID cards and BMC management tools.

A juju controller. You can find what is juju and how to deploy it [here](https://juju.is/docs/juju)


## DCGM prerequisites
In order to test DCGM, it's necessary to have a machine with NVIDIA GPU. If using testflinger, there are the following machines that can be used:
- nvidia-dgx-station-c25989 -> [NVIDIA Tesla V100](https://www.nvidia.com/en-gb/data-center/tesla-v100/)
- swob -> [NVIDIA L40S](https://www.nvidia.com/en-us/data-center/l40s/)
- plok -> [NVIDIA L40S](https://www.nvidia.com/en-us/data-center/l40s/)

It's recommended to install the drivers before installing hardware observer and this can be achieved by running:

```shell
sudo apt install nvidia-driver-<VERSION>-server
```

It might be necessary to reboot the machine in order to have the NVIDIA drivers modules loaded.

You can check if the installation was successful by running:

```shell
nvidia-smi
```

The output should look like this:
```
nvidia-smi
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 570.172.08             Driver Version: 570.172.08     CUDA Version: 12.8     |
|-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GeForce RTX 3050 ...    Off |   00000000:01:00.0  On |                  N/A |
| N/A   45C    P8              7W /   60W |      60MiB /   4096MiB |      0%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A           11418      G   /usr/bin/gnome-shell                     41MiB |
+-----------------------------------------------------------------------------------------+
```

If for some reason you forget to install the drivers before hardware-observer, you can run the following juju action:

```
juju run hardware-observer/0 redetect-hardware apply=true
```

## Set up juju and lxd and deploy hardware-observer
First, you need to bootstrap a Juju controller on a machine. For simplicity and convenience in this guide, we will use a default LXD controller. It's important to note that you can use any machine within the same network as the one you plan to deploy the hardware-observer on to serve as a controller. However, since we are utilizing only one physical machine in this setup, we will bootstrap an LXD controller on it.

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
To add the physical machine to the model, which is managed by a Juju controller on an LXD cloud, you need to allow the juju client to log into it via SSH as a user with sudo rights. On an Ubuntu machine, the `ubuntu` user typically satisfies this requirement:
```
cat ~/.local/share/juju/ssh/juju_id_rsa.pub >> ~/.ssh/authorized_keys
```

Now you can create a model and add your physical machine via the manual provider:
```
juju add-model hw-obs
# Use a different username if needed
# It is recommended to use the IP address of br0 for more reliable operation
BR0_ADDR=$(ip -4 -j a sho dev br0 | jq -r .[].addr_info[0].local)
juju add-machine ssh:ubuntu@$BR0_ADDR
```

### Deploy Hardware-Observer
```
juju switch hw-obs
juju deploy ubuntu --to 0
juju deploy hardware-observer
juju deploy opentelemetry-collector --channel 2/stable
```

Add necessary relations:
```
juju relate hardware-observer ubuntu
juju relate opentelemetry-collector ubuntu
juju relate opentelemetry-collector hardware-observer
```


## Set up microk8s and COS
### Set up microk8s
Set up microk8s. Steps can be found in this [guide](https://juju.is/docs/sdk/dev-setup#heading--manual-set-up-your-cloud).

Install microK8s package, it is required to use a strictly confined version:
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

Wait for microK8s to finish initialising:
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

Alias kubectl so it interacts with microK8s by default:
```
sudo snap alias microk8s.kubectl kubectl
```

Ensure your new group membership is apparent in the current terminal:
(Not required once you have logged out and back in again)
```
newgrp snap_microk8s
```

Juju recognises a local microK8s cloud automatically, bootstrap a microk8s controller:
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
juju relate opentelemetry-collector k8s-controller:cos.prometheus-receive-remote-write
juju relate opentelemetry-collector k8s-controller:cos.grafana-dashboards
juju relate opentelemetry-collector k8s-controller:cos.loki-logging
```


## Check the dashboard
Go to COS model and run:
```
juju run grafana/0 get-admin-password
```

This command will show the grafana dashboard endpoint and default password.  The default username is "admin".
Now you should be able to access grafana.

## Check DCGM
Check witch version of dcgm was installed by running:

```
sudo snap info dcgm
```

The channel should match a compatible driver version as explained in the [upstream doc](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html). E.g: If the driver version is >= 580, the charm should install from `v4-cuda13` track.

Other useful commands are:

```shell
# check is if the exporter is generating metrics
curl localhost:9400/metrics
```

``` shell
# enable persistence mode on each GPU. In this case there are 8 GPUs
for i in {0..7}; do sudo nvidia-smi -i "$i" -pm 1; done
```

```shell
# test discovery
dcgm.dcgmi discovery -l
```

NOTE: This check is currently failing because of lack of permissions on nv-hostengine. Check [#68](https://github.com/canonical/dcgm-snap/issues/68) for more details
```shell
# run diagnostics on the system
dcgm.dcgmi diag -r 1
```

```shell
# enable health checks
dcgm.dcgmi health --host localhost -s a

# run a health check
dcgm.dcgmi health --host localhost -g 0 -c -j
```
