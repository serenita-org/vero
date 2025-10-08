# Keymanager API

The [Ethereum Keymanager API](https://github.com/ethereum/keymanager-APIs){:target="_blank"}
is a standardized set of validator client API endpoints that
lets node operators manage validator keys. This API is
supported by many validator client implementations – see the Client
Support table
[here](https://github.com/ethereum/keymanager-APIs?tab=readme-ov-file#client-support){:target="_blank"}
for the most up-to-date information.

Through these API endpoints, node operators can add and remove
validator keys, override the fee recipient, graffiti, and gas limit
settings on a per-validator basis, all without needing to restart
the validator client.

## Vero support for the Keymanager API

As of `v1.1.0`, Vero supports the following Keymanager API endpoints:

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
