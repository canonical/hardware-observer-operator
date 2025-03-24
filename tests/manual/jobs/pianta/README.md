# Testable Exporters

- [x] Prometheus Hardware Exporter
  - [x] ipmi_dcmi
  - [x] ipmi_sel
  - [x] ipmi_sensor
  - [x] redfish
  - [ ] hpe_ssa
  - [ ] lsi_sas_2
  - [ ] lsi_sas_3
  - [ ] mega_raid
  - [x] poweredge_raid
- [ ] DCGM Exporter (require NVIDIA)
  - [ ] dcgm
- [x] Smartctl Exporter (require S.M.A.R.T disks)
  - [x] smartctl

## Resources

To test the above exporters, you will need to manually attach resource for `perccli-deb`. You can find the instruction
on how to download the resource [here](https://charmhub.io/hardware-observer/resources/perccli-deb). Once you downloaded
the resource, you can attach the resource using

```shell
juju attach-resource hardware-observer perccli-deb=<PATH-TO-PERCCLI-DEB>
```

## Redfish credential

Please consult the team for redfish credential.

After you have obtained the redfish credential, you can follow the steps to config Hardware Observer Operator to use
that redfish credential.

1. Enable the user: `sudo ipmitool user enable <USER-ID>`
2. Update charm config: `juju config hardware-observer redfish-username=<username> redfish-password=<password>`

As a good practice, you should disable the testing redfish user when you are done with testing: `sudo ipmitool userdisable <USER-ID>`.
