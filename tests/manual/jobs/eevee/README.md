# Testable Exporters

- [x] Prometheus Hardware Exporter
  - [x] ipmi_dcmi
  - [x] ipmi_sel
  - [x] ipmi_sensor
  - [x] redfish
  - [x] hpe_ssa (ssacli)
  - [ ] lsi_sas_2 (sas2ircu)
  - [ ] lsi_sas_3 (sas3ircu)
  - [ ] mega_raid (storcli)
  - [ ] poweredge_raid (perccli)
- [ ] DCGM Exporter (require NVIDIA)
  - [ ] dcgm
- [x] Smartctl Exporter (require S.M.A.R.T disks)
  - [x] smartctl

## Running the tests

You can run the functional tests for real hardware by following these steps:

```shell
# Adding relation will be tested as part of the test case, so we need to remove it before running the tests
juju remove-relation -m hw-obs hardware-observer grafana-agent

# We don't have redfish credential for this machine
juju config -m hw-obs hardware-observer redfish-disable=true

# Running the tests
tox -e func -- -v --realhw --model hw-obs --no-deploy  --collectors ipmi_dcmi ipmi_sel ipmi_sensor hpe_ssa  --keep-models
```
