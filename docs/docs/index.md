# Introduction

**Vero** is a multi-node validator client designed to protect validators
from client bugs. It does this by cross-checking the blockchain
state across multiple client implementations before submitting
attestations.

Vero works on both Ethereum and Gnosis Chain, and is compatible with
all Consensus Layer (CL) and Execution Layer (EL) clients.

## Design goals

1. ### Multi-node

    Vero is designed to take full advantage of client diversity by
    seamlessly [combining data from multiple clients](reference/using_multiple_beacon_nodes.md)
    at the same time.

    !!! question "What's the difference between a multi-node setup and a fallback setup?"

        In a fallback setup, secondary nodes are only
        used when the primary node goes offline.

        In a multi-node setup, all nodes are used simultaneously.

2. ### Security

    Validator clients form a critical part of staking infrastructure
    where security must be taken extremely seriously.

    To support this goal:

    - Vero never has direct access to validator keys.

        Instead, it works exclusively with **remote signers** like
        [Web3Signer](https://github.com/Consensys/web3signer){:target="_blank"}.

    - External dependencies are kept to a minimum, reducing the risk
       of supply chain attacks.

3. ### Simplicity

    Vero's codebase is intentionally kept small and focused.
    Less code means fewer potential bugs, making it easier to audit
    and reason about.

    <p align="center">
      <img alt="Overview" src="../assets/scatter-loc-dependencies.png" style="width: 30em;">
    </p>

    <p align="center">
      _Lines of code counted using `cloc` on September 20th 2025 (tests excluded)._
    </p>

4. ### Observability

    Understanding validator performance can be challenging.

    In support of this goal, Vero provides node operators with:

    - Clear, human-readable logs
    - Detailed [metrics and pre-built dashboards](reference/instrumentation.md#metrics)
    - Rich [tracing data](reference/instrumentation.md#tracing)

    Together, these help node operators better understand and optimize
    their setups.

5. ### Compatibility

    Vero must be compatible with all major CL and EL clients
    so it can reliably compare their views of the chain
    and determine which chain is safe to follow.

    In addition, Vero also supports industry standards like:

    - [Ethereum Remote Signing API](https://github.com/ethereum/remote-signing-api){:target="_blank"}
      (used by Web3Signer)
    - [Ethereum Keymanager API](https://github.com/ethereum/keymanager-APIs){:target="_blank"}
      (used by tools like Eth Docker and Dappnode)
