# Native

!!! info "Prerequisites"

    Make sure you're using Python 3.12 or later.

Install Vero's dependencies with your preferred package manager:

```bash
pip install -r requirements.txt
```

or

```bash
uv sync
```

You can now run Vero with:

```bash
python src/main.py <arguments>
```

For example:

```bash
python src/main.py \
  --network=hoodi \
  --remote-signer-url=http://signer:9000 \
  --beacon-node-urls=http://lighthouse:5052,http://lodestar:5052 \
  --fee-recipient=0x0000000000000000000000000000000000000000
```

See the [CLI Reference](../../reference/cli_reference.md) for a complete list of available arguments.
