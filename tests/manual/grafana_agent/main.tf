terraform {
  required_providers {
    juju = {
      version = "~> 0.17.0"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

module "grafana-agent" {
  source = "git::https://github.com/chanchiwai-ray/snap-openstack.git//sunbeam-python/sunbeam/features/observability/etc/deploy-grafana-agent?ref=fix-observability-feature"

  grafana-agent-base             = var.grafana_agent_base
  grafana-agent-channel          = "latest/stable"
  principal-application-model    = var.machine_model
  receive-remote-write-offer-url = var.receive-remote-write-offer-url
  grafana-dashboard-offer-url    = var.grafana-dashboard-offer-url
  logging-offer-url              = var.logging-offer-url

}

resource "juju_integration" "ubuntu-to-grafana-agent" {
  model = var.machine_model

  application {
    name     = var.ubuntu_name
    endpoint = "juju-info"
  }

  application {
    name     = "grafana-agent"
    endpoint = "juju-info"
  }
}

resource "juju_integration" "hardware-observer-to-grafana-agent" {
  model = var.machine_model

  application {
    name     = var.hardware_observer_name
    endpoint = "cos-agent"
  }

  application {
    name     = "grafana-agent"
    endpoint = "cos-agent"
  }
}
