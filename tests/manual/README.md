# Manual testing for Hardware Observer

Testing Hardware Observer Operator requires machines with various hardware devices (e.g. GPU, RAID controller, S.M.A.R.T
disks) that are not easily accessible to the CI environment. Fortunately, with [Testflinger][testflinger], we could
easily allocate physical machines with various hardware devices for testing. However, machines on testflinger can only
be reserved for 6 hours at most, so it can be quite cumbersome to reproduce the test environment for long term
development or testing. For this reason, we created a terraform plan that can easily deploys (or re-deploys) the
environment for testing Hardware Observer Operator with COS-Lite integrations.

> [!WARNING]
> This is not a production environment!

> [!WARNING]
> The use of testflinger is restricted. External contributor will not be able to use Testflinger to allocate physical
> machine. However, the terraform plan should still work if you somehow have access to a machine with hardware devices.

## Quick start

The overall workflow is outlined below:

```shell
# On the host machine (e.g. your laptop or desktop), run
git clone https://github.com/canonical/hardware-observer-operator.git
cd hardware-observer-operator/tests/manual/jobs
./submit.sh torchtusk noble lp:myusername-1234

# Wait until the machine is ready, then ssh into the machine
ssh ubuntu@xxx.xxx.xxx

# On the testflinger machine, run
git clone https://github.com/canonical/hardware-observer-operator.git
cd hardware-observer-operator/tests/manual/
./scripts/bootstrap.sh
terragrunt run-all apply
```

[testflinger]: https://canonical-testflinger.readthedocs-hosted.com/en/latest/
