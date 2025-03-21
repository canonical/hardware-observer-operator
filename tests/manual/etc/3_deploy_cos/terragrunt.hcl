dependency "add_machine" {
  config_path = "../1_add_machine"
  mock_outputs = {
    machine_model = "mocked_machine_model"
  }
}

dependency "add_k8s_cloud" {
  config_path = "../2_add_k8s_cloud"
  mock_outputs = {
    k8s_cloud_name       = "mocked_k8s_cloud_name"
    k8s_cloud_credential = "mocked_k8s_cloud_credential"
  }
}

terraform {
  after_hook "wait-for-cos" {
    commands     = ["apply"]
    execute      = [find_in_parent_folders("./scripts/wait-for-model.sh"), "cos"]
    run_on_error = true
  }

  after_hook "wait-for-cos-destroyed" {
    commands     = ["destroy"]
    execute      = [find_in_parent_folders("./scripts/wait-for-model-destroyed.sh"), "cos"]
    run_on_error = true
  }
}

inputs = {
  machine_model        = "${dependency.add_machine.outputs.machine_model}"
  k8s_cloud_name       = "${dependency.add_k8s_cloud.outputs.k8s_cloud_name}"
  k8s_cloud_credential = "${dependency.add_k8s_cloud.outputs.k8s_cloud_credential}"
  metallb_ip_ranges    = run_cmd("--terragrunt-quiet", find_in_parent_folders("./scripts/get-preferred-ip.sh"))
}
