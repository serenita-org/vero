# Why Vero

There are already several validator client implementations
– why do we need another one?

## Client Diversity

[Much](https://ethereum.org/en/developers/docs/nodes-and-clients/client-diversity/){:target="_blank"}
[has](https://clientdiversity.org/){:target="_blank"}
[been](https://www.reddit.com/r/ethstaker/comments/18xv282/quantifying_the_damage_a_supermajority_client_can/){:target="_blank"}
[written](https://research.lido.fi/t/ethereum-node-operator-el-diversity-improvement-commitments/6459){:target="_blank"}
about the importance of client diversity over the years. Bugs
in complex systems are unavoidable. In blockchain systems, they
can have severe consequences – from halting the chain to confirming
invalid transactions.
Ethereum has encouraged multiple teams to develop
independent implementations to reduce the impact of any
individual bug. But for the network to be resilient, all these
different implementations have to actually be used.
[A network where a (super)majority of validators runs the same client is not much better than a network that only runs a single client](https://dankradfeist.de/ethereum/2022/03/24/run-the-majority-client-at-your-own-peril.html){:target="_blank"}.

From the point of view of a node operator, switching to a fallback
client in case of a bug is far from enough as it can easily be too
late to react at that point – your validator may have already
attested to a buggy version of the chain. Exclusively using minority
clients works to a degree, but that is not a good long-term solution
as it relies on inaccurate self-reported client usage data.

## Where does Vero come in?

At [Serenita](https://serenita.io){:target="_blank"}, one of our
top priorities since the very beginning was to
ensure our validators do not vote for an invalid chain.
We started looking for a solution that would protect
against single-client bugs, regardless of how many others
used the buggy client. In practice, this meant verifying a single
client's view of the chain against another client's, both on the CL
and EL side.

We came across a few options that seemed to fulfill that requirement:

1. [Vouch](https://github.com/attestantio/vouch){:target="_blank"} combined with its majority attestation strategy
2. ~~DVT - [SSV](https://github.com/ssvlabs/ssv){:target="_blank"}~~ _(does not support attestation consensus)_
3. DVT - Obol's [Charon](https://github.com/ObolNetwork/charon){:target="_blank"}

The above options are solid choices. However, each of those
options also comes with some downsides.

1. **Vouch**

    Vouch does not support the
    [Ethereum remote signing API](https://github.com/ethereum/remote-signing-api){:target="_blank"}
    and is therefore not compatible with remote signing software like
    [Web3Signer](https://github.com/Consensys/web3signer){:target="_blank"}.
    This makes it non-trivial to switch to. **In case of an issue with Vouch,
    it would also be hard to switch back to a different setup.**

    Furthermore, Vouch has in a way become a victim of its own success – it
    is already being used by a lot of large node operators. And while there
    has never been an issue with it, if an issue were to occur, it would
    affect a large part of the network.

    *TLDR: not trivial to switch to, already used by a lot of large node operators*

2. **DVT - SSV**

    Managing validators on the ssv.network is expensive as a lot of data
    needs to be published in transactions on Ethereum mainnet.

    To run validators on the ssv.network, the SSV cluster also needs
    to pay a network fee. This requires managing and monitoring a balance
    of SSV tokens.

    At the time of writing it is not possible to
    configure an SSV cluster in a way that would prevent validators
    from voting for an invalid chain.

    *TLDR: expensive validator registrations, SSV token requirement*

3. **DVT - Obol's Charon**

    The Charon middleware client is not open-source, requiring an additional
    use grant from Obol for production use.

    Obol's team also took a different approach and did not implement their
    own validator client, instead choosing to go with a middleware approach,
    standing between existing validator clients and beacon nodes. That
    approach required some Charon-specific changes in beacon nodes.

    And again, any issue with Charon would be non-trivial to recover from.

    *TLDR: license, non-standard middleware approach*

___
The biggest shared risk for all of the above options was downtime.
An issue in any of the above implementations would require
an urgent fix from their respective maintainers. It would be
challenging to switch back to a different kind of setup in case
an issue were to occur.
**All three of the above solutions also share critical
dependencies, including:**

- `attestantio/go-eth2-client` (communication with beacon nodes)
- `ferranbt/fastssz`, `pk910/dynamic-ssz` (SSZ data manipulation, encoding/decoding)

A bug in any of those dependencies could easily affect all three
of the above at the same time.

___

In the end, we decided to implement a validator
client ourselves, and that's how the idea of Vero was born –
a simple, multi-node validator client that would protect our
validators from client bugs.

In August of 2024, we made Vero available to everyone
with a completely open-source license, hoping broader adoption
helps improve the resilience of the Ethereum network.

**With Vero and a multi-node setup, node operators no longer need to
worry about exact client usage data.** It is easy to switch to —and
switch back from— in case any issue were to occur.

!!! bug "What if there's a bug in Vero?"

    One of Vero's primary design goals is simplicity,
    which helps reduce the likelihood of bugs.
    While we can't guarantee that Vero will be entirely bug-free,
    we take several measures to minimize
    the risk of them occurring:

    - a small codebase – fewer lines of code mean fewer chances for bugs
    - high test coverage
    - regular cross-client integration testing in local devnets
      using [ethereum-package](https://github.com/ethpandaops/ethereum-package){:target="_blank"}

    If you do encounter an issue with Vero, you can switch to another validator
    client – ***easily, quickly and without slashing risk***.

## Feature comparison

### Attestation consensus

The validator client requires a threshold of connected clients
to agree on the state of the chain before voting for it.

|                | Attestation consensus |
|----------------|-----------------------|
| Vero           | ✅                     |
| Vouch          | ✅ (majority strategy) |
| Traditional VC | ❌                     |
| DVT - Charon   | ❌                     |
| DVT - SSV      | ❌                     |

### Slashing detection

Monitors slashing events on the network and immediately stops
performing validator duties as soon as any of the locally managed
validators get slashed.

|                | Slashing detection |
|----------------|--------------------|
| Vero           | ✅                  |
| Traditional VC | 🟠 (only Teku)     |
| DVT - Charon   | ❌                  |
| DVT - SSV      | ❌                  |
| Vouch          | ❌                  |

### Ethereum remote signing API

Supports remote signers using the
[Ethereum remote signing API](https://github.com/ethereum/remote-signing-api){:target="_blank"},
like [Web3Signer](https://docs.web3signer.consensys.io/){:target="_blank"}.

If you're already using a remote signer using this API, Vero is very easy
to switch to without any slashing risk (the slashing protection data
stays in-place). In case you end up not liking Vero, you can switch
back just as easily.

|                | Ethereum remote signing API |
|----------------|-----------------------------|
| Vero           | ✅                           |
| Traditional VC | ✅                           |
| Vouch          | ❌                           |
| DVT - Charon   | N/A                         |
| DVT - SSV      | N/A                         |

### Gnosis Chain support

Supports performing validator duties on Gnosis Chain.

|                | Gnosis Chain support |
|----------------|----------------------|
| Vero           | ✅                    |
| Traditional VC | ✅ (most of them)     |
| Vouch          | ❌                    |
| DVT - Charon   | ❌                    |
| DVT - SSV      | ❌                    |

### Open Source

Vero is completely open-source without any strings attached. It is released
as a public good to strengthen the Ethereum network, make running multi-node
setups more accessible and thereby improve the client diversity situation.

|                | Open Source |
|----------------|-------------|
| Vero           | ✅           |
| Traditional VC | ✅           |
| Vouch          | ✅           |
| DVT - SSV      | ✅           |
| DVT - Charon   | ❌           |
