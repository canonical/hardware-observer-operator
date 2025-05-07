terraform {
  required_providers {
    juju = {
      version = "~> 0.17.0"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}
resource "juju_kubernetes_cloud" "k8s_cloud" {
  name              = "k8s"
  kubernetes_config = file(var.kube_config)
}
