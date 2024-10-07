# Strategy Pattern in Hardware Observer

This document explains why we chose the strategy pattern for the hardware observer to handle the installation of required packages/tools.

## The Problem

### Different Installation Methods

In Hardware Observer, we need to support 10+ different hardware tools, each with its own installation method. Below are some examples of how these packages are installed:

- `apt install`.
- `apt install` from the vendor's repository.
- Manual attachment by the user using the `juju attach-resource` command.
- `snap install`.
- (deprecated) Download from GitHub releases.

### Required Workflow

In Hardware Observer, the charm automatically detects the hardware present on the machine and prompts the user to either attach the resource or install it automatically. To achieve this, we need to:

- Verify whether the packages/tools are already installed.
- Remove unnecessary packages when the charm runs the `remove` hook.

## Why Use the Strategy Pattern?

To meet these requirements, the strategy pattern provides an interface with three basic functions: `install`, `remove`, and `check`. Each hardware package or tool has its specific implementation encapsulated within this strategy interface. This creates a clear boundary between the low-level implementation (hardware tools install/remove/check strategy) and the high-level implementation (charm and exporter workflow). This provides several benefits:

- **One-way dependency**: When implementing the charm and exporter workflow, there’s no need to delve into the strategy details. These are already handled at the lower level. You only need to ensure that the required information, resources, and configurations are properly injected. This makes the exporter and charm logic easier to understand, refactor, test, and maintain.
- **Avoids a god class and allows for easy horizontal expansion**: A simple interface with multiple implementations makes it easier to support additional tools in the future.
- **Easier unit testing**: The boundary also separates pure and non-pure functions. Keeping the workflow functions as pure as possible makes unit testing simpler. A pure workflow function is much easier to maintain with unit tests.
- **Simplifies tuning and refactoring of high-level workflows**: Refactoring can be isolated to the high level due to the consistent interface between the layers.
- **Limit the size of PR**: For any future requirements or bug fixes, it's important to classify which part belongs to the low level and which part belongs to the high level. Seperate the PR to only relate to one of it can help to increate the quality of the PR.
