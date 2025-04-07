# Testable Exporters

- [x] Prometheus Hardware Exporter
  - [x] ipmi_dcmi
  - [x] ipmi_sel
  - [x] ipmi_sensor
  - [x] redfish
  - [ ] hpe_ssa (ssacli)
  - [ ] lsi_sas_2 (sas2ircu)
  - [ ] lsi_sas_3 (sas3ircu)
  - [x] mega_raid (storcli)
  - [ ] poweredge_raid (perccli)
- [ ] DCGM Exporter (require NVIDIA)
  - [ ] dcgm
- [x] Smartctl Exporter (require S.M.A.R.T disks)
  - [x] smartctl

## Resources

To test the above exporters, you will need to manually attach resource for `storcli-deb`. You can find the instruction
on how to download the resource [here](https://charmhub.io/hardware-observer/resources/storcli-deb). Once you downloaded
the resource, you can attach the resource using

```shell
juju attach-resource hardware-observer storcli-deb=<PATH-TO-STORCLI-DEB>
```
