terraform {
  after_hook "wait-for-microk8s" {
    commands     = ["apply"]
    execute      = ["../scripts/wait-for-microk8s.sh"]
    run_on_error = true
  }

  after_hook "wait-for-ubuntu" {
    commands     = ["apply"]
    execute      = ["../scripts/wait-for-ubuntu.sh"]
    run_on_error = true
  }

  after_hook "get-kubeconfig" {
    commands     = ["apply"]
    execute      = ["../scripts/get-kubeconfig.sh"]
    run_on_error = true
  }

  after_hook "cleanup" {
    commands     = ["destroy"]
    execute      = ["../scripts/cleanup.sh"]
    run_on_error = true
  }
}

inputs = {
  ssh_address      = format("ubuntu@%s", run_cmd("../scripts/get-local-ip.sh"))
  public_key_file  = format("%s/.ssh/id_rsa.pub", get_env("HOME"))
  private_key_file = format("%s/.ssh/id_rsa", get_env("HOME"))
}
