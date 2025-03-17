variable "machine_model" {
  description = "The machine model name"
}

variable "metallb_ip_ranges" {
  description = "The public IP addresses to services running in the Kubernetes cluster"
}

variable "k8s_cloud_name" {
  description = "The name of the k8s cloud"
}

variable "k8s_cloud_credential" {
  description = "The credential for the k8s cloud"
}
