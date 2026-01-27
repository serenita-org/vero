# CLI Reference

#### `--network`

**[required]** The network to use, one of `mainnet, gnosis, hoodi, chiado, custom`.

`custom` is a special case where Vero loads the network spec from the file specified using `--network-custom-config-path`

___

#### `--network-custom-config-path`

Path to a custom network configuration file.

___

#### `--remote-signer-url`

URL of the remote signer, e.g. `http://remote-signer:9000`.
If provided, Vero automatically handles duties for all validator keys
present on the remote signer.

!!! note ""

    This flag is mutually exclusive with `--enable-keymanager-api`.
    One of the two must be specified as the validator key source.

___

#### `--beacon-node-urls`

**[required]** A comma-separated list of beacon node URLs, e.g. `http://beacon-node-1:5052,http://beacon-node-2:5052,http://beacon-node-3:5052`

Vero [uses multiple beacon nodes](../reference/using_multiple_beacon_nodes.md) for most tasks like achieving attestation consensus,
producing blocks, and submitting duties.

??? note "More information"

    There are certain operations where only a single beacon node
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

A comma-separated list of beacon node URLs —e.g. `http://beacon-node-1:5052,http://beacon-node-2:5052,http://beacon-node-3:5052`—
to exclusively use for block proposals. When performing a block proposal duty,
only these beacon nodes will be used to produce and publish blocks.
___

#### `--attestation-consensus-threshold`

Specifies how many beacon nodes must agree on the attestation data
before the validators proceed to attest.

Defaults to a majority of beacon nodes (>50%) agreeing.

??? question "When should the default be overridden?"

    There are situations in which you may want to change the default:

    - When running against a large client-diverse set of beacon nodes
      where a lower threshold (like 3 out of 6 beacon nodes agreeing)
      may be sufficient to avoid single-client bugs.
    - To further minimize the risk of attesting to a wrong chain. If running
      against 5 different client implementations, you could increase
      the default majority threshold (3) to an even higher value like 4 or 5.
    - To temporarily increase your level of safety, e.g. around
      network upgrades when client bugs are more likely.

___

#### `--fee-recipient`

**[required]** The fee recipient address to use during block proposals.

Can be set individually for each validator through the [Keymanager API](../usage/keymanager_api.md).
___

#### `--data-dir`

The directory to use for storing persistent data. Defaults to `/vero/data`.
___

#### `--graffiti`

The graffiti string to use during block proposals. Defaults to an empty string.

Can be set individually for each validator through the [Keymanager API](../usage/keymanager_api.md).
___

#### `--gas-limit`

The gas limit value passed on to external block builders
during validator registrations.

Can be set individually for each validator through the [Keymanager API](../usage/keymanager_api.md).

!!! note ""

    This setting does _not_ affect the gas limit value
    of the connected CL or EL clients.

??? note "Default values"

    | Network  | Gas Limit |
    |:---------|----------:|
    | mainnet  |  60000000 |
    | gnosis   |  17000000 |
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

Defaults to `90`. This means an externally built block must be
~11% more valuable to be chosen over a locally built block.
___

#### `--enable-doppelganger-detection`

Enables doppelganger detection during startup.

??? note "More information"

    When enabled, Vero pauses its validator duties for up to three epochs
    while it scans the network for attestations (or any other signs that
    your validator keys are already active elsewhere). If activity is
    detected, Vero aborts startup.

    Do not rely on this as your only protection against running the same
    keys in two places—it's a best‑effort safeguard only.

    **Notes**

    - You may need to explicitly enable liveness tracking on your primary
    connected beacon node.
    - Keys hot‑loaded via the Keymanager API become active immediately;
    doppelganger detection will only be attempted on Vero's next startup.
    - Operational Tip: Restart Vero in the final slots of an epoch to
    minimize missed attestations.

___

#### `--enable-keymanager-api`

Enables Vero's [Keymanager API](../usage/keymanager_api.md).

!!! note ""

    This flag is mutually exclusive with `--remote-signer-url`.
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

#### `--log-level`

The logging level to use, one of `CRITICAL, ERROR, WARNING, INFO, DEBUG`. Defaults to `INFO`.

___

#### `--ignore-spec-mismatch`

Ignores a mismatch between spec values returned by a beacon node and
spec values included in Vero (which normally prevents such beacon nodes
from being used).

This flag can be used when a beacon node does not yet support new spec
values (e.g. for upcoming network upgrades).

___

### Dangerous Flags

??? danger "Expand"

    The flags below should not be used under normal circumstances.

    ??? danger "`----DANGER----disable-slashing-detection`"

        ⚠️ **_This flag is extremely dangerous and should not be provided to Vero under normal circumstances._**

        **_Do not provide this flag unless you fully understand its implications!_**

        Disables Vero's proactive slashing detection.

        With this flag provided, Vero will keep attesting and producing blocks
        even if it detects some of its managed validators have been slashed.
