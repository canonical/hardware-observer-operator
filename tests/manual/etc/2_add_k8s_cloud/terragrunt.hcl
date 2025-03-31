dependency "add_machine" {
  config_path  = "../1_add_machine"
  skip_outputs = true
}

terraform {
  before_hook "create-dot-kube-dir" {
    commands = ["plan"]
    execute  = ["mkdir", "-p", format("%s/.kube", get_env("HOME"))]
  }

  before_hook "touch-kubeconfig" {
    commands = ["plan"]
    execute  = ["touch", format("%s/.kube/config", get_env("HOME"))]
  }
}

inputs = {
  kube_config = format("%s/.kube/config", get_env("HOME"))
}
