# List of Testflinger Jobs for Hardware Observer Manual Tests

This directory contains a list of job queues on [testflinger][testflinger] that can be used for testing hardware
observer manually. Each job queue is defined in a directory with a `README.md` that indicates the testable items on that
machine.

> [!Note]
> You can only submit job defined in this directory!

The `./submit.sh` script is a simple wrapper for `testflinger submit` that allow user to submit the jobs with customize
[`distro`][job-schema] and [`ssk_keys`][ssh-keys] (only support one ssh keys).

## Quick Start

You can allocate a physical machine using the `./submit.sh` script. For example, to allocate machine from job queue
[`torchtusk`](./torchtusk), and use ubuntu:24.04 (noble) as the OS image, and import ssh key using launchpad ID
`lp:myusername-1234`. Run

```shell
$ ./submit.sh torchtusk jammy lp:myusername-1234
# job.yaml
job_queue: torchtusk
provision_data:
    distro: noble
reserve_data:
ssh_keys:
    - lp:myusername-1234
timeout: 21600
Job submitted successfully!
job_id: 25a3b103-26dd-421c-817d-2950f968d327
```

Then, wait for the machine to become available

```shell
$ testflinger poll 25a3b103-26dd-421c-817d-2950f968d327

***************************************************
* Starting testflinger reserve phase on torchtusk *
***************************************************

...

Number of key(s) added: 3

Now try logging into the machine, with:   "ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' 'ubuntu@xxx.xxx.xxx.xxx'"
and check to make sure that only the key(s) you wanted were added.

*** TESTFLINGER SYSTEM RESERVED ***
You can now connect to ubuntu@xxx.xxx.xxx.xxx
Current time:           [2025-03-17T05:40:47.103464]
Reservation expires at: [2025-03-17T11:40:47.103513]
Reservation will automatically timeout in 21600 seconds
To end the reservation sooner use: testflinger-cli cancel 25a3b103-26dd-421c-817d-2950f968d327
```

Finally, you can login to the machine using the command provided

```shell
ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' 'ubuntu@xxx.xxx.xxx.xxx'  # IP address is redarted
```

## Contributing

Please add more job queues to this directory to increase test coverage for Hardware Observer. An example contribution of
job queue can be something like the following:

```text
torchtusk/
├── job.tpl.yaml
└── README.md
```

where the **name of the directory** is the `job_queue`; the file **job.tpl.yaml** is the [job defintion][job-schema];
and `README.md` contains the testable items on that machine.


[testflinger]: https://certification.canonical.com/docs/ops/tel-labs-docs/how-to/use_machines_through_testflinger/
[job-schema]: https://canonical-testflinger.readthedocs-hosted.com/en/latest/reference/job-schema.html
[ssk-keys]: https://canonical-testflinger.readthedocs-hosted.com/en/latest/reference/test-phases.html#reserve
