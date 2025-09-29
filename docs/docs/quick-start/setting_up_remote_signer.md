# Setting up the remote signer

For security reasons, Vero never interacts directly with
validator keys. Instead, key management is handled by a
remote signer, such as [Web3Signer](https://docs.web3signer.consensys.io/){:target="_blank"}:

```mermaid
flowchart LR

RS(Remote Signer) <--> V(Vero)

style V fill:#11497E,stroke:#000000
```

This improves security, but it makes the initial setup
a little more complicated.

For this quick-start guide, we'll be making
our life easier and use [eth-docker](https://ethdocker.com/){:target="_blank"}
to set up both the remote signer and Vero.
Perform the following steps on the machine you intend to run
Vero on:

1. Clone eth-docker into a new "vero" directory

    ```bash

    cd ~

    git clone https://github.com/ethstaker/eth-docker.git vero

    cd vero
    ```

2. Create a copy of the default config file

    ```bash
    cp default.env .env
    ```

3. Edit the config file

    ```bash
    nano .env
    ```

    then edit the following lines as needed:

    ```
    COMPOSE_FILE=vero-vc-only.yml:web3signer.yml
    FEE_RECIPIENT=0xYourEthereumAddress # Replace with your own fee recipient
    NETWORK=the network to use, hoodi or mainnet
    WEB3SIGNER=true
    CL_NODE=http://beacon-node:5052
    ```

    Adjust the `CL_NODE` URL as needed – replace `beacon-node:5052` with
    the IP address or hostname and API port of the CL client you set up
    earlier.

___

!!! tip "Let's check everything is set up correctly"

We still haven't imported our validator keys. However, we can check
if everything is set up correctly so far.

Run `./ethd up` to start Vero and the remote signer.
Then, run `/ethd logs validator` to view Vero's logs.

If you've set everything up correctly, you should see lines
like these in the logs:

```
WARNING: No active or pending validators detected
```
