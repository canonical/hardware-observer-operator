# DCGM prerequisites
In order to test DCGM, it's necessary to have a machine with NVIDIA GPU. If using testflinger, there are the following machines that can be used:
- torchtusk -> [NVIDIA Tesla V100](https://www.nvidia.com/en-gb/data-center/tesla-v100/)
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

> **Note:**  If for some reason you forget to install the NVIDIA drivers before hardware-observer, you can run:
```shell
juju run hardware-observer/0 redetect-hardware apply=true
```

# Testable Exporters



- [x] Prometheus Hardware Exporter
  - [x] ipmi_dcmi
  - [x] ipmi_sel
  - [x] ipmi_sensor
  - [x] redfish
  - [ ] hpe_ssa (ssacli)
  - [ ] lsi_sas_2 (sas2ircu)
  - [ ] lsi_sas_3 (sas3ircu)
  - [ ] mega_raid (storcli)
  - [ ] poweredge_raid (perccli)
- [x] DCGM Exporter (require NVIDIA)
  - [x] dcgm
- [x] Smartctl Exporter (require S.M.A.R.T disks)
  - [x] smartctl

# Check DCGM

Check which version of dcgm was installed by running:

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
