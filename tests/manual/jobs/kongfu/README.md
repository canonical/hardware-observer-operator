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

## Running the tests

You can run the functional tests for real hardware by following these steps:

```shell
# Adding relation will be tested as part of the test case, so we need to remove it before running the tests
juju remove-relation -m hw-obs hardware-observer opentelemetry-collector

# We don't have redfish credential for this machine
juju config -m hw-obs hardware-observer redfish-disable=true

# If you already attach the `storcli-deb` resource
tox -e func -- -v -k 'not test_required_resources' --realhw --model hw-obs --no-deploy  --collectors ipmi_dcmi ipmi_sel ipmi_sensor mega_raid  --keep-models
```
