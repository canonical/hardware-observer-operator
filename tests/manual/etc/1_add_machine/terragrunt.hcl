terraform {
  after_hook "wait-for-ubuntu" {
    commands     = ["apply"]
    execute      = [find_in_parent_folders("./scripts/wait-for-application.sh"), "hw-obs", "ubuntu"]
    run_on_error = true
  }

  after_hook "wait-for-microk8s" {
    commands     = ["apply"]
    execute      = [find_in_parent_folders("./scripts/wait-for-application.sh"), "hw-obs", "microk8s"]
    run_on_error = true
  }
  after_hook "get-kubeconfig" {
    commands     = ["apply"]
    execute      = [find_in_parent_folders("./scripts/get-kubeconfig.sh")]
    run_on_error = true
  }

  after_hook "cleanup" {
    commands     = ["destroy"]
    execute      = [find_in_parent_folders("./scripts/cleanup.sh")]
    run_on_error = true
  }
}

inputs = {
  ssh_address      = format("ubuntu@%s", run_cmd("--terragrunt-quiet", find_in_parent_folders("./scripts/get-local-ip.sh")))
  public_key_file  = format("%s/.ssh/id_rsa.pub", get_env("HOME"))
  private_key_file = format("%s/.ssh/id_rsa", get_env("HOME"))
}
