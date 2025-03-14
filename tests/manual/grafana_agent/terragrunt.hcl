dependency "cos" {
  config_path = "../cos"
}

dependency "machine" {
  config_path = "../machine"
}

terraform {
  after_hook "wait-for-grafana-agent" {
    commands     = ["apply"]
    execute      = ["../scripts/wait-for-grafana-agent.sh"]
    run_on_error = true
  }
}

inputs = {
  machine_model                  = "${dependency.machine.outputs.model_name}"
  grafana_agent_base             = "${dependency.machine.outputs.machine_base}"
  ubuntu_name                    = "${dependency.machine.outputs.ubuntu_name}"
  hardware_observer_name         = "${dependency.machine.outputs.hardware_observer_name}"
  receive-remote-write-offer-url = "${dependency.cos.outputs.receive-remote-write-offer-url}"
  grafana-dashboard-offer-url    = "${dependency.cos.outputs.grafana-dashboard-offer-url}"
  loki-logging-offer-url         = "${dependency.cos.outputs.loki-logging-offer-url}"
}
