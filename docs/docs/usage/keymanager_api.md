# Keymanager API

The [Ethereum Keymanager API](https://github.com/ethereum/keymanager-APIs){:target="_blank"}
is a standardized set of validator client API endpoints that
lets node operators manage validator keys. This API is
supported by many validator client implementations – see the Client
Support table
[here](https://github.com/ethereum/keymanager-APIs?tab=readme-ov-file#client-support){:target="_blank"}
for the most up-to-date information.

Through these API endpoints, node operators can add and remove
validator keys, override the fee recipient, graffiti, gas limit, and builder
settings on a per-validator basis, all without needing to restart
the validator client.

## Vero support for the Keymanager API

Vero supports the following Keymanager API endpoints:

- [Builder Config](https://ethereum.github.io/keymanager-APIs/#/Builder%20Config){:target="_blank"}
- [Fee Recipient](https://ethereum.github.io/keymanager-APIs/#/Fee%20Recipient){:target="_blank"}
- [Gas Limit](https://ethereum.github.io/keymanager-APIs/#/Gas%20Limit){:target="_blank"}
- [Graffiti](https://ethereum.github.io/keymanager-APIs/#/Graffiti){:target="_blank"}
- [Remote Key Manager](https://ethereum.github.io/keymanager-APIs/#/Remote%20Key%20Manager){:target="_blank"}
- [Voluntary Exit](https://ethereum.github.io/keymanager-APIs/#/Voluntary%20Exit){:target="_blank"}

!!! info "Unsupported endpoints"

    The _Local Key Manager_ endpoints are not supported since Vero does
    not manage validator keys directly.

___

## API Authorization

All Keymanager API endpoints require a value to be set in the `Authorization`
header. The header value is expected to have the following format:

`Bearer HEX-ENCODED-TOKEN`

You can generate the token yourself and have Vero use your token
value by specifying the `--keymanager-api-token-file-path` CLI argument.
If you don't provide a token, Vero will generate one and write
it to a file called `keymanager-api-token.txt` in its data directory.

___

## Using the Keymanager API

Vero determines which validators to start performing duties for in one
of two ways, depending on the CLI arguments that are provided to it.

That is why the following two CLI options are mutually exclusive – only
one of them can be used at a time.

1. Providing the `--remote-signer-url` CLI flag

    In this case, Vero simply starts using all validator keys loaded
    on the remote signer. The Keymanager API is disabled in this mode.
    In this mode, Vero will use the same graffiti, gas limit and
    fee recipient values for all validators.

2. **Providing the keys to use via the Keymanager API**

    In this case, you enable the Keymanager API (`--enable-keymanager-api`).

    Next, you must instruct Vero which keys to load using the
    Remote Key Manager API endpoints. This requires sending an
    HTTP POST request to the `/eth/v1/remotekeys` API endpoint,
    telling Vero exactly which validator keys to use and
    where to find them.

    !!! note "Example HTTP request"

        ```bash
        curl -X POST http://vero:8001/eth/v1/remotekeys \
        -H "accept: application/json" \
        -H  "Content-Type: application/json" \
        -H "Authorization: Bearer 0011abcd0011abcd0011abcd0011abcd0011abcd0011abcd0011abcd0011abcd" \
        -d '{"remote_keys":[{"pubkey": "0x94907e04363dfa47348ca42225f221f0c57396181d1124013587271c6b681ebc8584fd3e6e8d4ec69b8358969976b260", "url": "http://web3signer:9000"}]}'
        ```

    !!! info "You only need to do this once"

        There's no need to resend the request each time Vero restarts.

        Vero persists the submitted data in its database.

Once you have your keys loaded via the Keymanager API, you can then use
the rest of the Keymanager API endpoints to e.g. override the fee recipient
address for specific validators.

Refer to the [Keymanager API spec](https://ethereum.github.io/keymanager-APIs/){:target="_blank"}
for details on available endpoints and parameters.

## Per-validator builder configuration

Use `/eth/v1/validator/{pubkey}/builder_config` to configure how a validator
sources builder bids. These settings are persisted and apply without restarting Vero,
both when Vero selects bids itself and when selection is delegated to beacon nodes.
Builder entries and their bid limits apply to Gloas proposals.

- `GET` returns the fully resolved configuration, including defaults from the CLI.
- `POST` replaces the validator's entire configuration and returns `202`.
- `DELETE` restores the CLI defaults and returns `204`.

For example, this configuration sets a minimum bid of 10,000,000 Gwei and uses
one builder, with a maximum execution payment of 250,000,000 Gwei:

```json
{
  "min_bid": "10000000",
  "builder_boost_factor": "100",
  "builders": [
    {
      "url": "https://builder.example.com",
      "max_execution_payment": "250000000"
    }
  ]
}
```

Omitted `min_bid` and `builder_boost_factor` values inherit the CLI settings.
Individual builder entries can override those values; otherwise they inherit the
validator's values. An omitted `max_execution_payment` inherits
`--builder-max-execution-payment`. All numeric values are uint64 decimal strings.
The maximum execution payment defaults to `0`. When Vero selects bids, it rejects
any bid whose trusted execution payment exceeds this limit, regardless of its
in-protocol payment. A payment equal to the limit is accepted, and accepted bids
are valued at their full in-protocol plus execution payment before applying the
boost factor. This is intentionally stricter than the Keymanager API's scoring-cap
semantics. If bid selection is delegated to beacon nodes, Vero forwards the limits
and those nodes enforce their own selection policy.

Omitting `builders` uses `--builder-urls`, while `"builders": []` disables direct
builder bids for this validator. P2P bids remain available and follow the validator's
top-level minimum bid and boost factor. Posting `{}` or deleting the configuration
restores all CLI defaults. Reposting a resolved `GET` response's `data` fixes its
values instead of continuing to inherit changes to defaults.

Each entry can include opaque hex-encoded `auth_data` and a `builder_pubkeys`
allowlist. Authentication defaults to the builder URL's hostname; an omitted or
empty allowlist accepts any builder. The same URL can appear more than once with
different authentication data. Duplicate URL and authentication pairs are rejected,
including pairs differing only in the hex letter case of `auth_data`.
