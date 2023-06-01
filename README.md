<!--
Avoid using this README file for information that is maintained or published elsewhere, e.g.:

* metadata.yaml > published on Charmhub
* documentation > published on (or linked to from) Charmhub
* detailed contribution guide > documentation or CONTRIBUTING.md

Use links instead.
-->

# charm-prometheus-hardware-exporter

Charmhub package name: charm-prometheus-hardware-exporter
More information: https://charmhub.io/charm-prometheus-hardware-exporter


The charm to install the exporter which export hardware metrices for IPMI, RedFish and RAID devices from different vendor.

## Other resources

<!-- If your charm is documented somewhere else other than Charmhub, provide a link separately. -->

- [Read more](https://example.com)

- [Contributing](CONTRIBUTING.md) <!-- or link to other contribution documentation -->

- See the [Juju SDK documentation](https://juju.is/docs/sdk) for more information about developing and improving charms.


## Features

- [ ] Resources management
    - [x] Upload resources to `$SNAP_COMMON/bin` folder
    - [ ] Action: List resources

- [ ] Exporter and monitor part
    - [ ] Build relation with COS

- [x] Snap install
    - [x] Download libs `charms.operator_libs_linux.v2.snap`
