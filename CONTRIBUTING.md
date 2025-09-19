# Contributing

Great to have you here as a future contributor!

## Basic guidelines

We try to adhere to the [Zen of Python](https://peps.python.org/pep-0020/),
preferring simple code over complex code.
Some of the code style and behavior is enforced using pre-commit
hooks like `ruff` and `mypy`.

Any changes to Vero should align with its design goals (listed in the [README](./README.md)).

### Simple changes

Did you find a bug that is simple to fix? Or find a way to make something
perform better with minimal changes?

Feel free to create a PR right away, we love these kinds of PRs
and will try to address them promptly!

*Note on typo PRs: Due to people abusing PRs to public
cryptocurrency-related repositories in the hopes of receiving
airdrops, trivial typo PRs may not be merged at the discretion
of the maintainers.*

### Significant changes

Vero's feature set and codebase have intentionally been kept to a minimum.
This has two primary reasons - security and maintainability.

For these reasons, large additions of code, complex changes, introductions
of significant new features or introductions of new external dependencies
may not be merged unless the advantages these changes bring are also
significant.

If you're considering working on a larger change that has not
been discussed, please create an issue to discuss it before working on it.

### Development

We use [uv](https://docs.astral.sh/uv/) to manage project dependencies but
you can use any other dependency management tool including `pip`.

Any larger change is required to be tested on a local devnet
using the Kurtosis
[ethereum-package](https://github.com/ethpandaops/ethereum-package)
in which Vero is a supported validator client option.
The process is very simple: build a Vero image locally and
specify it under `vc_image` in your local network configuration.

#### Tests

To run tests locally, install the project dev requirements:

_(`uv sync` also installs the dev dependency group by default)_
```shell
uv sync
```

Then run `uv run pytest`.

If you're not using `uv`, make sure to install the dependencies
from both `requirements.txt` and `requirements-dev.txt`.


### Linting

This repository uses pre-commit hooks for linting.
`pre-commit` is included as a dev dependency. It is
necessary to manually install the git hooks by running
`uv run pre-commit install`. A pre-commit hook is then
automatically ran before every change you commit.
You can also manually run the hooks without commiting by running
`uv run pre-commit run --all-files`.
