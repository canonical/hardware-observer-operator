output "machine_model" {
  value = juju_model.hw-obs.name
}
output "ubuntu_name" {
  value = juju_application.ubuntu.name
}

output "hardware_observer_name" {
  value = juju_application.hardware-observer.name
}

output "machine_base" {
  value = juju_machine.machine.base
}
