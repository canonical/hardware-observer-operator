dependency "machine" {
  config_path = "../machine"
}

inputs = {
  kube_config = format("%s/.kube/config", get_env("HOME"))
}
