terraform {
  required_providers {
    juju = {
      version = "= 1.3.1"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

module "opentelemetry-collector" {
  source = "git::https://github.com/canonical/snap-openstack.git//sunbeam-python/sunbeam/features/observability/etc/deploy-grafana-agent?ref=fa2e56ce687c046b4c931512564787eac419e3ab"

  opentelemetry-collector-base     = var.opentelemetry_collector_base
  opentelemetry-collector-channel  = "2/stable"
  principal-application-model-uuid = var.machine_model_uuid
  receive-remote-write-offer-url   = var.receive-remote-write-offer-url
  grafana-dashboard-offer-url      = var.grafana-dashboard-offer-url
  logging-offer-url                = var.loki-logging-offer-url

}

resource "juju_integration" "ubuntu-to-opentelemetry-collector" {
  model_uuid = var.machine_model_uuid

  application {
    name     = var.ubuntu_name
    endpoint = "juju-info"
  }

  application {
    name     = "opentelemetry-collector"
    endpoint = "juju-info"
  }
}

resource "juju_integration" "hardware-observer-to-opentelemetry-collector" {
  model_uuid = var.machine_model_uuid

  application {
    name     = var.hardware_observer_name
    endpoint = "cos-agent"
  }

  application {
    name     = "opentelemetry-collector"
    endpoint = "cos-agent"
  }
}
