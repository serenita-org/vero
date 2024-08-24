# Contributing

Great to have you here as a future contributor!

## Basic guidelines

We try to adhere to the [Zen of Python](https://peps.python.org/pep-0020/),
preferring simple code over complex code.
Some of the code style and behavior is enforced using pre-commit
hooks like `ruff` and `mypy`.

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

### Tests

To run tests locally, install the dev requirements:

```shell
pip install -r requirements-dev.txt
```

Then run `pytest`.


### Linting

This repository uses pre-commit hooks for linting. In order
to run these locally, first install pre-commit
(`pip install pre-commit`).
You should then be able to run `pre-commit run --all-files`.
