output "k8s_cloud_name" {
  value = juju_kubernetes_cloud.k8s_cloud.name
}

output "k8s_cloud_credential" {
  value = juju_kubernetes_cloud.k8s_cloud.credential
}
