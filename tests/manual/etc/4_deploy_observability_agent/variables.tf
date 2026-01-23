variable "machine_model" {
  description = "The machine model name"
}

variable "opentelemetry_collector_base" {
  description = "The base for opentelemetry-collector"
}

variable "ubuntu_name" {
  description = "The name of ubuntu charm"
  default     = "ubuntu"
}

variable "hardware_observer_name" {
  description = "The name of hardware observer charm"
  default     = "hardware observer"
}

variable "receive-remote-write-offer-url" {
  description = "Offer URL from prometheus-k8s:receive-remote-write application"
  type        = string
  default     = null
}

variable "grafana-dashboard-offer-url" {
  description = "Offer URL from grafana-k8s:grafana-dashboard application"
  type        = string
  default     = null
}

variable "loki-logging-offer-url" {
  description = "Offer URL from loki-k8s:logging application"
  type        = string
  default     = null
}
