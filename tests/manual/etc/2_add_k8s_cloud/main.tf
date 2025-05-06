terraform {
  required_providers {
    juju = {
      version = "~> 0.17.0"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

resource "null_resource" "wait_for_microk8s" {
  provisioner "local-exec" {
    command = "sudo microk8s status --wait-ready"
  }
}
resource "juju_kubernetes_cloud" "k8s_cloud" {
  name              = "k8s"
  kubernetes_config = file(var.kube_config)
  depends_on        = [null_resource.wait_for_microk8s]
}
