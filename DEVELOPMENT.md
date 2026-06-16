# Development

## Setup environment

To start working on this charm, you'll need a working [development setup](https://juju.is/docs/sdk/dev-setup).

Install `uv` and `tox` (once):

```shell
sudo snap install astral-uv --classic
uv tool install tox --with tox-uv
```

Set up the local development environment:

```shell
uv sync --all-groups
source .venv/bin/activate
```

## Testing

This project uses `tox` for managing test environments. There are some pre-configured environments
that can be used for linting and formatting code when you're preparing contributions to the charm:

```shell
tox -e reformat     # update your code according to linting rules
tox -e lint         # code style
tox -e unit         # unit tests
tox -e integration  # integration tests
tox                 # runs 'lint' and 'unit' environments
```

## Build the charm

Build the charm in this git repository using:

```shell
charmcraft pack
```

<!-- You may want to include any contribution/style guidelines in this document>
