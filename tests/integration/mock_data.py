# Metrics
SAMPLE_METRICS = [
    {
        "name": "ipmi_dcmi_command_success",
        "documentation": "Indicates if the ipmi dcmi command is successful or not",
        "labels": {},
        "value": 0.0,
    },
    {
        "name": "redfish_call_success",
        "documentation": "Indicates if call to the redfish API succeeded or not",
        "labels": {},
        "value": 1.0,
    },
    {
        "name": "ipmi_temperature_celsius",
        "documentation": "Temperature measure from temperature sensors",
        "labels": {"name": "testname", "state": "Critical", "unit": "C"},
        "value": 200,
    },
]


# Expected alerts based on above metrics
EXPECTED_ALERTS = [
    {
        "labels": {
            "alertname": "IPMIDCMICommandFailed",
            "juju_application": "hardware-observer",
            "juju_unit": "hardware-observer/0",
            "severity": "critical",
        },
        "state": "firing",
        "value": 0.0,
    },
    {
        "labels": {
            "alertname": "IPMITemperatureStateNotOk",
            "juju_application": "hardware-observer",
            "juju_unit": "hardware-observer/0",
            "severity": "critical",
        },
        "state": "firing",
        "value": 200,
    },
]
