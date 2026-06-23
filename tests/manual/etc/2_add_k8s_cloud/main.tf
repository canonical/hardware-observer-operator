terraform {
  required_providers {
    juju = {
      version = "= 1.3.1"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

resource "juju_kubernetes_cloud" "k8s_cloud" {
  name               = "k8s"
  kubernetes_config  = file(var.kube_config)
  storage_class_name = "microk8s-hostpath"
}
