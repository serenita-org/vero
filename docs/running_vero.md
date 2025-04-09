# Running Vero

## Prerequisites

- In order to use Vero, you will need to use a remote signer
to manage your validator keys. The remote signer **must be**
connected to a slashing protection database - **Vero does
not maintain its own slashing protection database!**

## Local build

Get started by using the correct version of Python - 3.12 .

Next, install the dependencies using the package manager of your choice:

```
pip install -r requirements.txt
```

You should now be able to run Vero:

```
python src/main.py <arguments>
```


## Docker

You can build the image yourself using the included [Dockerfile](../Dockerfile) or you can use the official image.

```
 docker run ghcr.io/serenita-org/vero:<version> <arguments>
 ```

Check out the [example docker compose file](../compose-example.yaml).


# CLI Reference

#### `--network`

**[required]** The network to use, one of `mainnet,gnosis,holesky,hoodi,chiado,custom`.

`custom` is a special case where Vero loads the network spec from the file specified using `--network-custom-config-path`
___

#### `--network-custom-config-path`

Path to a custom network configuration file from which to load the network specs.
___

#### `--remote-signer-url`

**[required]** URL of the remote signer, e.g. `http://remote-signer:9000`
___

#### `--beacon-node-urls`

**[required]** A comma-separated list of beacon node URLs, e.g. `http://beacon-node-1:5052,http://beacon-node-2:5052,http://beacon-node-3:5052`
___

#### `--beacon-node-urls-proposal`

A comma-separated list of beacon node URLs, e.g. `http://beacon-node-1:5052,http://beacon-node-2:5052,http://beacon-node-3:5052` to
exclusively use for block proposals. When performing a block proposal duty,
only these beacon nodes will be used to produce and publish a block.
___

#### `--attestation-consensus-threshold`

Specify the required number of beacon nodes that need to agree
on the attestation data before the validators proceed to attest.

There are a few situations where you may want to change the default:
- when running against 2 beacon nodes, where you only want to use
  the second node as a fallback
- when running against a large client-diverse set of beacon nodes
  where a lower threshold (like 2 or 3 out of 6 beacon nodes agreeing)
  may be sufficient to avoid single-client bugs.

See https://github.com/serenita-org/vero/issues/38 for more
information.

Defaults to a majority of beacon nodes (>50%) agreeing.
___

#### `--fee-recipient`

**[required]** The fee recipient address to use during block proposals.
___

#### `--graffiti`

The graffiti string to use during block proposals. Defaults to an empty string.
___

#### `--gas-limit`

The gas limit value to pass on to external block builders
during validator registrations. *Note: this does not affect the gas limit value
of the connected CL or EL clients.*

Current defaults per network:
```
mainnet: 36M
gnosis: 17M
holesky: 36M
hoodi: 36M
chiado: 17M
custom: 100M
```

___

#### `--use-external-builder`

Provide this flag to submit validator registrations to external builders.
___

#### `--builder-boost-factor`

A percentage multiplier applied to externally built blocks when comparing their value
to locally built blocks. The externally built block is only chosen if its value,
post-multiplication, is higher than the locally built block's value. Defaults to `90`.
___

#### `--data-dir`

The directory to use for storing persistent data. Defaults to `/vero/data`.
___

#### `--metrics-address`

The metrics server listen address. Defaults to `localhost`.
___

#### `--metrics-port`

The metrics server listen port. Defaults to `8000`.
___

#### `--metrics-multiprocess-mode`

Provide this flag to collect metrics from all processes. This comes with some limitations, notably no cpu and memory metrics. See https://prometheus.github.io/client_python/multiprocess/ .
___

#### `--log-level`

The logging level to use, one of `CRITICAL,ERROR,WARNING,INFO,DEBUG`. Defaults to `INFO`.
___

#### `---DANGER----disable-slashing-detection`

**_!!! This flag is extremely dangerous and should not be provided to Vero under normal circumstances!!!_**

**_Do not provide this flag unless you fully understand its implications!_**

Disables Vero's proactive slashing detection.

With this flag provided, Vero will keep attesting and producing blocks
even if it detects some of its managed validators have been slashed.
___
