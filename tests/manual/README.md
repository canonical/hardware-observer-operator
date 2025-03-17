# Manual testing for Hardware Observer

## Quick start

1. Allocate a physical machine from [./jobs](./jobs) directory.
2. Copy the deployment [./etc](./etc) to the physical machine.
3. In the machine, run `./scripts/bootstrap.sh` to bootstrap the Juju controller.
4. In the machine, run `terrgrunt run-all apply`
