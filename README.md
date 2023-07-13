<!--
Avoid using this README file for information that is maintained or published elsewhere, e.g.:

* metadata.yaml > published on Charmhub
* documentation > published on (or linked to from) Charmhub
* detailed contribution guide > documentation or CONTRIBUTING.md

Use links instead.
-->
[![Charmhub Badge](https://charmhub.io/hardware-observer/badge.svg)](https://charmhub.io/hardware-observer)
[![Release Edge](https://github.com/canonical/hardware-observer-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/hardware-observer-operator/actions/workflows/release.yaml)

# hardware-observer-operator

Charmhub package name: hardware-observer
More information: https://charmhub.io/hardware-observer


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
