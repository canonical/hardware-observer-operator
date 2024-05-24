# Functional Tests for the Hardware Observer Charm
There are 2 main types of functional tests for the Hardware Observer charm - those which depend on real hardware to be present and those that can run without it.

Here, "real hardware" refers to machines that are not VMs or containers and have access to real hardware resources like RAID cards and BMC management tools.

## Hardware Independent Tests
These are the tests for hardware observer that do not require any real hardware.

Hardware independent tests are run on every PR / weekly scheduled test run. They belong to the `TestCharm` class in the `test_charm.py` module.

These include:
* Testing whether juju config changes produce the required results
* Check whether the exporter systemd service starts and stops correctly
* Test exporter is stopped and related files removed on removal of charm

and more.

Running these tests is as simple as executing the `make functional` command.

## Hardware Dependent Tests
These are the tests that depend on real hardware to be executed. This is performed manually when required, for example - validating the charm's full functionality before a new release.

Hardware dependent tests are present in the `TestCharmWithHW` class in the `test_charm.py` module. The pytest marker `realhw` has been added to this class (which would include all the tests in this class).

These tests will only be executed if the `--collectors` option for pytest is provided some value. Otherwise, all these tests are skipped (this is done by checking for the presence of the `realhw` marker mentioned earlier.)

Note: The `test_build_and_deploy` function sets up the test environment for both types of tests.

Some of these tests include:
* Check if all collectors are detected in the exporter config file
* Test if metrics are available at the expected endpoint
* Test if metrics specific to the collectors being tested are available

and more.

In order to run these tests, a couple of prerequisite steps need to be completed.
1. Setup test environment
2. Add environment variables for Redfish credentials.
3. Setup required resource files
4. Find supported collectors

### 1. Setup test environment
For the hardware dependent tests, we add the test machine beforehand and the bundle only handles deploying the applications to this machine.

We would need 2 machines which are in the same network. One of them will be bootstrapped as a controller (can be VM or container) for the juju manual cloud we will be creating and the other will be added as a machine into the model.

A basic outline of the steps would look like:
```
# Add manual cloud to juju
$ juju add-cloud manual-cloud --client

Select cloud type: manual
ssh connection string for controller: user@$IP_CONTROLLER

# Bootstrap controller on the machine
$ juju bootstrap manual-cloud manual-controller

# Add model and machine
$ juju add-model test

$ juju add-machine ssh:user@IP_MACHINE_FOR_TESTING
```

### 2. Add environment variables for Redfish credentials
As part of the redfish collector specific tests, redfish credentials need to be provided for authentication.

Therefore, the test expects these environment variables to be set:
* `REDFISH_USERNAME`
* `REDFISH_PASSWORD`

### 3. Setup required resource files
Create a new `resources` directory in the root of the project.
Check which collectors are supported on the machine and verify if they need to be manually downloaded (refer https://charmhub.io/hardware-observer/resources/).
Download the required resource files from their respective third-party websites and add the extracted `.deb` file or binary to this directory.

Note: The tests expect these resources to be named exactly in the manner provided below:
* storcli.deb
* perccli.deb
* sas2ircu
* sas3ircu

### 4. Find supported collectors
Note down all the collectors supported by the machine as they need to be provided to pytest as part of its CLI arguments.

This is done by passing the required collectors in a space-separated manner via the `FUNC_ARGS` environment variable to the make target.

The supported collectors can be found by checking the output of the `lshw` command (for RAID cards) or checking availability of Redfish and IPMI on the BMC.

---

### Running the tests

After ensuring the prerequisite steps are complete, the final command to run the tests would look something like this:
```
FUNC_ARGS="--model test --collectors ipmi_dcmi ipmi_sel ipmi_sensor redfish mega_raid" make functional
```

This would pass the required collectors to tox which then sends it to the pytest command and starts the hardware dependent tests.

### Troubleshooting

Create a `pytest.ini` file with the following contents to follow the live pytest logs

```
[pytest]
log_cli = True
log_cli_level = INFO
```

Add this line if you'd like to pass some more pytest options without messing with the make command.
```
addopts = -vv -k 'ipmi_sensor'
```
