output "model_name" {
  value = local.cos_model_name
}

output "receive-remote-write-offer-url" {
  value = module.cos-lite-terraform.prometheus-receive-remote-write-offer-url
}

output "opentelemetry-collector-offer-url" {
  value = module.cos-lite-terraform.opentelemetry-collector-offer-url
}

output "loki-logging-offer-url" {
  value = module.cos-lite-terraform.loki-logging-offer-url
}
