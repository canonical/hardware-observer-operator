terraform {
  required_providers {
    juju = {
      version = "= 1.3.1"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

locals {
  cos_model_name = "cos"
}

module "cos-lite-terraform" {
  source = "git::https://github.com/canonical/snap-openstack.git//sunbeam-python/sunbeam/features/observability/etc/deploy-cos?ref=fa2e56ce687c046b4c931512564787eac419e3ab"

  model      = local.cos_model_name
  cloud      = var.k8s_cloud_name
  region     = "default"
  credential = var.k8s_cloud_credential

  config = {
    workload-storage = "microk8s-hostpath"
  }

  alertmanager-channel = "1/stable"
  prometheus-channel   = "1/stable"
  grafana-channel      = "1/stable"
  catalogue-channel    = "1/stable"
  loki-channel         = "1/stable"
}

data "juju_model" "cos" {
  owner      = "admin"
  name       = local.cos_model_name
  depends_on = [module.cos-lite-terraform]
}

resource "juju_application" "metallb" {
  name  = "metallb"
  trust = true
  units = 1

  model_uuid = data.juju_model.cos.uuid
  config = {
    iprange = var.metallb_ip_ranges
  }

  charm {
    name    = "metallb"
    channel = "latest/stable"
    base    = "ubuntu@22.04"
  }

  depends_on = [module.cos-lite-terraform, data.juju_model.cos]

}
