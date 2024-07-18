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
To integrate hardware-observer with COS, you can follow this [guide](https://charmhub.io/hardware-observer/docs/integrate-with-cos)


## Check the dashboard
Go to COS model and run:
$ juju run grafana/0 get-admin-password

This command will show the dashboard endpoint and default password, the default uername is "admin".
Now you should be able to access the dashboard.