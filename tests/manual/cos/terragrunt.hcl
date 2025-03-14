dependency "machine" {
  config_path = "../machine"
}

dependency "k8s_cloud" {
  config_path = "../k8s_cloud"
}

terraform {
  after_hook "wait-for-cos" {
    commands     = ["apply"]
    execute      = ["../scripts/wait-for-cos.sh"]
    run_on_error = true
  }

  after_hook "wait-for-cos-model-destroyed" {
    commands     = ["destroy"]
    execute      = ["../scripts/wait-for-cos-model-destroyed.sh"]
    run_on_error = true
  }
}

inputs = {
  k8s_cloud_name       = "${dependency.k8s_cloud.outputs.name}"
  k8s_cloud_credential = "${dependency.k8s_cloud.outputs.credential}"
  machine_model        = "${dependency.machine.outputs.model_name}"
  metallb_ip_ranges    = run_cmd("../scripts/get-preferred-ip.sh")
}
