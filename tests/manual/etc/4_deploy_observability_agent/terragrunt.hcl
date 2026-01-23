dependency "add_machine" {
  config_path = "../1_add_machine"
  mock_outputs = {
    machine_base           = "mocked_os@mocked_release"
    machine_model          = "mocked_machine_model"
    ubuntu_name            = "mocked_ubuntu_name"
    hardware_observer_name = "mocked_hardware_observer_name"
  }
}

dependency "deploy_cos" {
  config_path = "../3_deploy_cos"
  mock_outputs = {
    receive-remote-write-offer-url = "mocked_receive-remote-write-offer-url"
    grafana-dashboard-offer-url    = "mocked_grafana-dashboard-offer-url"
    loki-logging-offer-url         = "mocked_loki-logging-offer-url"
  }
}

terraform {
  after_hook "wait-for-opentelemetry-collector" {
    commands     = ["apply"]
    execute      = [find_in_parent_folders("./scripts/wait-for-application.sh"), "hw-obs", "opentelemetry-collector"]
    run_on_error = true
  }
}

inputs = {
  machine_model                  = "${dependency.add_machine.outputs.machine_model}"
  opentelemetry_collector_base   = "${dependency.add_machine.outputs.machine_base}"
  ubuntu_name                    = "${dependency.add_machine.outputs.ubuntu_name}"
  hardware_observer_name         = "${dependency.add_machine.outputs.hardware_observer_name}"
  receive-remote-write-offer-url = "${dependency.deploy_cos.outputs.receive-remote-write-offer-url}"
  grafana-dashboard-offer-url    = "${dependency.deploy_cos.outputs.grafana-dashboard-offer-url}"
  loki-logging-offer-url         = "${dependency.deploy_cos.outputs.loki-logging-offer-url}"
}
