<!--
Avoid using this README file for information that is maintained or published elsewhere, e.g.:

* metadata.yaml > published on Charmhub
* documentation > published on (or linked to from) Charmhub
* detailed contribution guide > documentation or CONTRIBUTING.md

Use links instead.
-->
[![Charmhub Badge](https://charmhub.io/hardware-observer/badge.svg)](https://charmhub.io/hardware-observer)
[![Release Edge](https://github.com/canonical/hardware-observer-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/canonical/hardware-observer-operator/actions/workflows/release.yaml)

# Hardware Observer Operator

## Overview
[Charmhub Page](https://charmhub.io/hardware-observer)

Hardware-observer is a [subordinate machine charm](https://juju.is/docs/sdk/charm-taxonomy#heading--subordinate-charms) that provides monitoring and alerting of hardware resources on bare-metal infrastructure.

Hardware-observer collects and exports Prometheus metrics from BMCs (using the IPMI and newer Redfish protocols) and various SAS and RAID controllers through the use of the [prometheus-hardware-exporter](https://github.com/canonical/prometheus-hardware-exporter) project. It additionally configures Prometheus alert rules that are fired when the status of any metric is suboptimal.

Appropriate collectors and alert rules are installed based on the availability of one or more of the RAID/SAS controllers mentioned below:

- Broadcom MegaRAID controller
- Dell PowerEdge RAID Controller
- LSI SAS-2 controller
- LSI SAS-3 controller
- HPE Smart Array controller

This charm is ideal for monitoring hardware resources when used in conjunction with the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack).

## Uploading Resources

In order to manage third-party hardware resources, vendor-specific CLI tools need to be uploaded via `juju attach-resource`.

In the [Resources page](https://charmhub.io/hardware-observer/resources) on Charmhub, the name of the resource along with the download URL can be found.


## Other Links

<!-- If your charm is documented somewhere else other than Charmhub, provide a link separately. -->

- [Contributing](CONTRIBUTING.md) <!-- or link to other contribution documentation -->

- See the [Juju SDK documentation](https://juju.is/docs/sdk) for more information about developing and improving charms.
