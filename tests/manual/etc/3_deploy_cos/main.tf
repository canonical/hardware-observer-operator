terraform {
  required_providers {
    juju = {
      version = "~> 0.17.0"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

locals {
  cos_model_name = "cos"
}

module "cos-lite-terraform" {
  source = "git::https://github.com/canonical/snap-openstack.git//sunbeam-python/sunbeam/features/observability/etc/deploy-cos"

  model      = local.cos_model_name
  cloud      = var.k8s_cloud_name
  region     = "default"
  credential = var.k8s_cloud_credential

  config = {
    workload-storage = "microk8s-hostpath"
  }
}

resource "juju_application" "metallb" {
  name  = "metallb"
  trust = true
  units = 1

  model = local.cos_model_name
  config = {
    iprange = var.metallb_ip_ranges
  }

  charm {
    name    = "metallb"
    channel = "latest/stable"
    base    = "ubuntu@22.04"
  }

  depends_on = [module.cos-lite-terraform]

}
