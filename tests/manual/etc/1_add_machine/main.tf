terraform {
  required_providers {
    juju = {
      version = "=1.3.1"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

resource "juju_model" "hw-obs" {
  name = "hw-obs"

  cloud {
    name = "localhost"
  }
}

resource "juju_machine" "machine" {
  model_uuid = juju_model.hw-obs.uuid

  ssh_address      = var.ssh_address
  public_key_file  = var.public_key_file
  private_key_file = var.private_key_file
}

resource "juju_application" "ubuntu" {
  name       = "ubuntu"
  model_uuid = juju_model.hw-obs.uuid

  machines = [juju_machine.machine.machine_id]

  charm {
    name    = "ubuntu"
    base    = juju_machine.machine.base
    channel = "latest/stable"
  }
}

resource "juju_application" "microk8s" {
  name       = "microk8s"
  model_uuid = juju_model.hw-obs.uuid

  machines = [juju_machine.machine.machine_id]
  config = {
    hostpath_storage = true
  }

  charm {
    name    = "microk8s"
    base    = juju_machine.machine.base
    channel = "1.28/stable"
  }
}

resource "juju_application" "hardware-observer" {
  name       = "hardware-observer"
  model_uuid = juju_model.hw-obs.uuid

  charm {
    name    = "hardware-observer"
    base    = juju_machine.machine.base
    channel = "latest/stable"
  }
}

resource "juju_integration" "ubuntu-to-hardware-observer" {
  model_uuid = juju_model.hw-obs.uuid

  application {
    name     = juju_application.ubuntu.name
    endpoint = "juju-info"
  }

  application {
    name     = juju_application.hardware-observer.name
    endpoint = "general-info"
  }
}
