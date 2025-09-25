# Running Vero

## Prerequisites

- To use Vero, you must use a remote signer to manage your validator
  keys — Vero intentionally never has direct access to validator keys.
- The remote signer **must be** connected to a slashing protection
  database — **Vero does not maintain its own slashing protection
  database!**


## Docker

You can build the image yourself using the included [Dockerfile](../Dockerfile) or you can use the official image.

```bash
docker run ghcr.io/serenita-org/vero:<version> <arguments>
 ```

Check out the [example docker compose file](../compose-example.yaml).

You can also run Vero through the popular [eth-docker](https://ethdocker.com/) project.
A multi-client Vero-powered setup is described [in the eth-docker docs](https://ethdocker.com/Usage/Advanced/Vero).

## Local build

<details>
<summary>Expand</summary>

Ensure you're using Python 3.12.

Next, install the dependencies using the package manager of your choice:

```bash
pip install -r requirements.txt
```

or

```bash
uv sync
```

You should now be able to run Vero:

```bash
python src/main.py <arguments>
```

</details>


# CLI Reference

#### `--network`

**[required]** The network to use, one of `mainnet,gnosis,holesky,hoodi,chiado,custom`.

`custom` is a special case where Vero loads the network spec from the file specified using `--network-custom-config-path`
___

#### `--network-custom-config-path`

Path to a custom network configuration file from which to load the network specs.
___

#### `--remote-signer-url`

URL of the remote signer, e.g. `http://remote-signer:9000`.
If provided, Vero automatically handles duties for all validator keys
present on the remote signer.

_Note: This flag is mutually exclusive with `--enable-keymanager-api`.
One of the two must be specified as the validator key source._
___

#### `--beacon-node-urls`

**[required]** A comma-separated list of beacon node URLs, e.g. `http://beacon-node-1:5052,http://beacon-node-2:5052,http://beacon-node-3:5052`

Vero uses multiple beacon nodes for most tasks like achieving attestation consensus,
producing blocks and submitting duties.

However, there are certain operations where only a single beacon node
is used. In these cases, Vero will default to the first beacon node
in your list – unless its score drops (e.g., it goes offline or
responds slowly). If that happens, Vero automatically fails over
to the next highest-scoring beacon node.

Single-node operations include:

- Fetching duties
- Publishing validator registrations to MEV relays
  - To avoid overloading relays with duplicate registrations, only one
    beacon node is used.
  - For this reason it's important that your first listed beacon node
    is connected to mev-boost (or commit-boost) and all the relays you
    intend to use.
- Subscribing to the beacon chain event stream

___

#### `--beacon-node-urls-proposal`

A comma-separated list of beacon node URLs, e.g. `http://beacon-node-1:5052,http://beacon-node-2:5052,http://beacon-node-3:5052` to
exclusively use for block proposals. When performing a block proposal duty,
only these beacon nodes will be used to produce and publish a block.
___

#### `--attestation-consensus-threshold`

Specify the required number of beacon nodes that need to agree
on the attestation data before the validators proceed to attest.

Defaults to a majority of beacon nodes (>50%) agreeing.

There are a few situations where you may want to change the default:
- When running against 2 beacon nodes, where you only want to use
  the second node as a fallback – set the threshold to 1.
- When running against a large client-diverse set of beacon nodes
  where a lower threshold (like 2 or 3 out of 6 beacon nodes agreeing)
  may be sufficient to avoid single-client bugs.
- To further minimize the risk of attesting to a wrong chain. If running
  against 5 different client implementations, you might want to increase
  the default majority threshold (3) to an even higher value like 4 or 5.
  _Note: a high threshold may negatively affect your validator's
  performance._

___

#### `--fee-recipient`

**[required]** The fee recipient address to use during block proposals.

Can be set individually for each validator through the [Keymanager API](https://ethereum.github.io/keymanager-APIs/).
___

#### `--data-dir`

The directory to use for storing persistent data. Defaults to `/vero/data`.
___

#### `--graffiti`

The graffiti string to use during block proposals. Defaults to an empty string.

Can be set individually for each validator through the [Keymanager API](https://ethereum.github.io/keymanager-APIs/).
___

#### `--gas-limit`

The gas limit value to pass on to external block builders
during validator registrations.

Can be set individually for each validator through the [Keymanager API](https://ethereum.github.io/keymanager-APIs/).

*Note: this does not affect the gas limit value
of the connected CL or EL clients.*

Defaults to the following values:

| Network  | Gas Limit |
|:---------|----------:|
| mainnet  |  45000000 |
| gnosis   |  17000000 |
| holesky  |  60000000 |
| hoodi    |  60000000 |
| chiado   |  17000000 |
| custom   | 100000000 |
___

#### `--use-external-builder`

Provide this flag to submit validator registrations to external builders.
___

#### `--builder-boost-factor`

A percentage multiplier applied to externally built blocks when comparing their value
to locally built blocks. The externally built block is only chosen if its value,
post-multiplication, is higher than the locally built block's value.

Defaults to `90`, meaning the externally built block must be approximately
11% more valuable to be chosen over a locally built block.
___

#### `--enable-doppelganger-detection`

Enables doppelganger detection during start-up.

When enabled, Vero pauses its validator duties for up to three epochs
while it scans the network for attestations (or any other signs that
your validator keys are already active elsewhere). If activity is
detected, Vero aborts start‑up.

> Don’t rely on this as your sole protection against running the same
keys in two places—it’s a best‑effort safeguard only.

**Notes**
- You may need to explicitly enable liveness tracking on your primary
connected beacon node.
- Keys hot‑loaded via the Keymanager API become active immediately;
doppelganger detection will only be attempted on Vero’s next start‑up.
- Operational Tip: Restart Vero in the final slots of an epoch to
minimise missed attestations.

___

#### `--enable-keymanager-api`

Enables the [Keymanager API](https://ethereum.github.io/keymanager-APIs/).

_Note: This flag is mutually exclusive with `--remote-signer-url`.
One of the two must be specified as the validator key source._
___

#### `--keymanager-api-token-file-path`

Path to a file containing the bearer token used for Keymanager API
authentication. If no path is provided, a file called
`keymanager-api-token.txt` will be created in Vero's data directory.

___

#### `--keymanager-api-address`

The Keymanager API server listen address. Defaults to `localhost`.

___

#### `--keymanager-api-port`

The Keymanager API server port number. Defaults to `8001`.

___

#### `--metrics-address`

The metrics server listen address. Defaults to `localhost`.
___

#### `--metrics-port`

The metrics server listen port. Defaults to `8000`.
___

#### `--metrics-multiprocess-mode`

Provide this flag to collect metrics from all processes. This comes with some limitations, notably no CPU and memory metrics. See https://prometheus.github.io/client_python/multiprocess/ .
___

#### `--log-level`

The logging level to use, one of `CRITICAL,ERROR,WARNING,INFO,DEBUG`. Defaults to `INFO`.
___

#### `----DANGER----disable-slashing-detection`

**_!!! This flag is extremely dangerous and should not be provided to Vero under normal circumstances!!!_**

**_Do not provide this flag unless you fully understand its implications!_**

Disables Vero's proactive slashing detection.

With this flag provided, Vero will keep attesting and producing blocks
even if it detects some of its managed validators have been slashed.
___
