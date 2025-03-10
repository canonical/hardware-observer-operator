# Functional Tests for the Hardware Observer Charm
There are 2 main types of functional tests for the Hardware Observer charm - those which depend on
real hardware to be present and those that can run without it.

Here, "real hardware" refers to machines that are not VMs or containers and have access to real
hardware resources like RAID cards and BMC management tools.

Note: the built charm must be present in the root of the project's directory for the tests to run.

## Hardware Independent Tests
These are the tests for hardware observer that do not require any real hardware.

Hardware independent tests are run on every PR / weekly scheduled test run.

These include:
* Testing whether juju config changes produce the required results

Running these tests is as simple as executing the `tox -e func -- -v`

## Hardware Dependent Tests
These are the tests that depend on real hardware to be executed. This is performed manually when
required, for example - validating the charm's full functionality before a new release.

Hardware dependent tests are present in the `TestCharmWithHW` class in the `test_charm.py` module.
The pytest marker `realhw` has been added to this class (which would include all the tests in this
class).

These tests will only be executed if the `--realhw` option for pytest is provided. Additionally,
the `--collectors` option with space separated values can be provided, if specific hardware is
present. Check the `conftest.py` for options. Otherwise, all these tests are skipped (this is done
by checking for the presence of the `realhw` marker mentioned earlier.)

Note: The operator must set up a test model with the machine added beforehand. The machine must be
an actual host, containers or VMs won't work.
Note: depending on the test, certain prerequisites are needed, e.g. having set up an nvidia driver.
Check the tests' docstrings for details.

Some of these tests include:
* Check if all collectors are detected in the exporter config file
* Test if metrics are available at the expected endpoint
* Test if metrics specific to the collectors being tested are available
* Test if smarctl-exporter snap is installed and running
* Test if the dcgm snap is installed

and more.

In order to run these tests, several prerequisites may need to be completed.
1. Setup test environment
1. Build the charm
1. Add environment variables for Redfish credentials (if testing redfish).
1. Setup required resource files (if testing hardware raid).
1. Install the NVIDIA gpu driver and add the `--nvidia` flag (if testing NVIDIA gpu observability).
1. Find supported collectors

### 1. Setup test environment

You can refer to dev-environment.md here, up to the "Add physical machine" section included.
The end result should be a test model with a manually provisioned machine listed:

```
$ juju status
Model  Controller      Cloud/Region         Version  SLA          Timestamp
test   lxd-controller  localhost/localhost  3.6.1    unsupported  01:39:10Z

Machine  State    Address      Inst id             Base          AZ  Message
0        started  10.239.17.1  manual:10.239.17.1  ubuntu@22.04      Manually provisioned machine
```

### 2. Build the charm

Just run `charmcraft pack` from the project directory.

### 3. Add environment variables for Redfish credentials
As part of the redfish collector specific tests, redfish credentials need to be provided for
authentication.

Therefore, the test expects these environment variables to be set:
* `REDFISH_USERNAME`
* `REDFISH_PASSWORD`

### 4. Setup required resource files
Create a new `resources` directory in the root of the project.
Check which collectors are supported on the machine and verify if they need to be manually
downloaded (refer https://charmhub.io/hardware-observer/resources/).  Download the required
resource files from their respective third-party websites and add the extracted `.deb` file or
binary to this directory.

Note: The tests expect these resources to be named exactly in the manner provided below:
* storcli.deb
* perccli.deb
* sas2ircu
* sas3ircu

### 4. Find supported collectors
Note down all the collectors supported by the machine as they need to be provided to pytest as part
of its CLI arguments.

This is done by passing the required collectors in a space-separated manner via `--collector`
option to the tox target.

The supported collectors can be found by checking the output of the `lshw` command (for RAID cards)
or checking availability of Redfish and IPMI on the BMC.

---

### Running the tests

After ensuring the prerequisite steps are complete, the final command to run the tests would look
something like this:

```
tox -e func -- -v --realhw --model test --collectors ipmi_dcmi ipmi_sel ipmi_sensor redfish mega_raid --nvidia --keep-models
```

This would pass the required collectors to tox which then sends it to the pytest command and starts
the hardware dependent tests.

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
