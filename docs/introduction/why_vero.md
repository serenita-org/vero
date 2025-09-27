# Why Vero

There are already several validator client implementations, you
might be wondering why we need another one.

## Client Diversity

[Much](https://ethereum.org/en/developers/docs/nodes-and-clients/client-diversity/){:target="_blank"}
[has](https://clientdiversity.org/){:target="_blank"}
[been](https://www.reddit.com/r/ethstaker/comments/18xv282/quantifying_the_damage_a_supermajority_client_can/){:target="_blank"}
[written](https://research.lido.fi/t/ethereum-node-operator-el-diversity-improvement-commitments/6459){:target="_blank"}
about the importance of client diversity over the years. Bugs
in complex systems are unavoidable. In blockchain systems they
can have severe consequences, ranging from chains halting all
the way to invalid data being confirmed by the network.
Ethereum has encouraged multiple teams to develop
independent implementations to reduce the impact of any
individual bug. But for the network to be resilient, all these
different implementations have to actually be used.
[A network where a (super)majority of validators runs the same client is not much better than a network that only runs a single client](https://dankradfeist.de/ethereum/2022/03/24/run-the-majority-client-at-your-own-peril.html){:target="_blank"}.

From the point of view of a node operator, switching to a fallback
client in case of a bug is far from enough as it can easily be too
late to react at that point - your validator may have already
attested to a buggy version of the chain. Exclusively using minority
clients works, but that does not seem like a good long-term solution
as it relies on self-reported client usage data which has a hard time
taking into account multi-node and/or DVT setups.

## Where does Vero come in?

At [Serenita](https://serenita.io){:target="_blank"}, one of our
top priorities since the very beginning was to
ensure our validators do not attest to a chain that is only
considered valid by a single client implementation
(which could be due to a bug in that client). Our envisioned solution
would protect us from single-client bugs no matter how many others
used the client in question. In practice this means verifying a single
client's view of the chain against another client's, both on the CL
and EL side.

We found a few options that seemed to fulfill that requirement:

1. [Vouch](https://github.com/attestantio/vouch){:target="_blank"} combined with its majority attestation strategy
2. DVT - [SSV](https://github.com/ssvlabs/ssv){:target="_blank"}
3. DVT - Obol's [Charon](https://github.com/ObolNetwork/charon){:target="_blank"}

All of the above options are solid choices. However, each of those
options also comes with some downsides.

1. **Vouch**

    Vouch does not support the
    [Ethereum remote signing API](https://github.com/ethereum/remote-signing-api){:target="_blank"}
    and is therefore not compatible with remote signing software like
    [Web3Signer](https://github.com/Consensys/web3signer){:target="_blank"}.
    This makes it non-trivial to switch to. **In case of an issue with Vouch,
    it would also be hard to switch back to a different setup.**

    Furthermore, Vouch has in a way become a victim of its own success - it
    is already being used by a lot of large node operators. And while there
    has never been an issue with it, if an issue were to occur, it would
    affect a large portion of the network.

    *TLDR: not trivial to switch to, already used by a lot of large NOs*

2. **DVT - SSV**

    Registering validators with the ssv.network is expensive, as encrypted
    partial validator keys need to be published in transactions on Ethereum
    mainnet.

    To run validators on the ssv.network, the SSV cluster needs
    to pay a network fee. This requires managing and monitoring a balance
    of SSV tokens.

    *TLDR: expensive validator registrations, SSV token requirement*

3. **DVT - Obol's Charon**

    The Charon middleware client is not open-source, requiring an additional
    use grant from Obol for production use.

    Obol's team also took a different approach and did not implement their
    own validator client, instead choosing to go with a middleware approach,
    standing between existing validator clients and beacon nodes. That
    approach required some Charon-specific changes in beacon nodes.
    Again, any issue with Charon would be non-trivial to recover from.

    *TLDR: license, non-standard middleware approach*

___
The biggest shared risk for all of the above options was downtime.
An issue in any of the above implementations would require
an urgent fix from their respective maintainers. It would be
challenging to switch back to a different kind of setup in case of
an issue. **An interesting fact about all three of the above solutions is
that they all share a common and pretty critical dependency,
namely `attestantio/go-eth2-client` which implements the logic
used to communicate with beacon nodes. A bug in that dependency
could easily affect all three of the above at the same time.**

In the end, we decided it could be fun to implement a validator
client ourselves and that's how the idea of Vero was born –
a simple multi-node validator client that would protect our
validators from client bugs.

In August of 2024, we made Vero available to everyone
with a completely open-source license, hoping broader adoption
helps improve the resilience of the Ethereum network.

**With Vero and a multi-node setup, node operators no longer need to
worry about exact client usage data.** It is easy to switch to —and
switch back from— in case any issue were to occur.

!!! question "What if there's a bug in Vero?"

    Vero is a lot less complex than Ethereum clients. And while we
    there will never be a guarantee of Vero being bug-free,
    we take every possible measure we can to minimize the chances
    of serious bugs within Vero:

    - a small codebase - the more lines of code, the higher the chance of a bug
    - high test coverage
    - regular cross-client integration testing in local devnets
      using [ethereum-package](https://github.com/ethpandaops/ethereum-package){:target="_blank"}

    Still, if you encounter an issue with Vero, you can switch to any
    other validator client – *easily, quickly and without slashing risk*.

## Feature comparison

### Attestation consensus

- Requests data from multiple beacon nodes before attesting.
- Only attests if a majority of them agrees on the attestation data.
- Can tolerate a minority of beacon nodes going offline.

|                | Attestation consensus             |
|----------------|-----------------------------------|
| Traditional VC | ❌                                 |
| DVT - Charon   | ✅                                 |
| DVT - SSV      | ✅                                 |
| Vouch          | ✅ (majority attestation strategy) |
| Vero           | ✅                                 |

### Slashing detection

Monitors slashing events on the network and immediately stops
performing validator duties as soon as any of the locally managed
validators get slashed.

|                | Slashing detection |
|----------------|--------------------|
| Traditional VC | 🟠 (only Teku)     |
| DVT - Charon   | ❌                  |
| DVT - SSV      | ❌                  |
| Vouch          | ❌                  |
| Vero           | ✅                  |

### Ethereum remote signing API

Supports remote signers using the
[Ethereum remote signing API](https://github.com/ethereum/remote-signing-api){:target="_blank"}.

If you're already using a remote signer using this API, Vero is very easy
to switch to without any slashing risk (the slashing protection data
stays in-place). In case you end up not liking Vero, you can switch
back just as easily.

|                | Ethereum remote signing API |
|----------------|-----------------------------|
| Traditional VC | ✅                           |
| DVT - Charon   | ✅                           |
| DVT - SSV      | ❌                           |
| Vouch          | ❌                           |
| Vero           | ✅                           |

### Gnosis Chain support

Supports performing validator duties on Gnosis Chain.

**Medium to large node operators on Gnosis Chain - read this!** There are
not many options when it comes to EL clients on Gnosis Chain. Nethermind
likely has a supermajority there. With only 2 nodes, Vero allows you to
run Nethermind and Erigon side-by-side and only attest if both of the
implementations agree. That way you never risk getting stuck on a buggy
supermajority chain!

|                | Gnosis Chain support |
|----------------|----------------------|
| Traditional VC | ✅ (most of them)     |
| DVT - Charon   | ❓                    |
| DVT - SSV      | ❌                    |
| Vouch          | ❌                    |
| Vero           | ✅                    |

### Open Source

Vero is completely open-source without any strings attached. It is released
as a public good to strengthen the Ethereum network, make running multi-node
setups more accessible and thereby improve the client diversity situation.

|                | Open Source |
|----------------|-------------|
| Traditional VC | ✅           |
| DVT - Charon   | ❌           |
| DVT - SSV      | ✅           |
| Vouch          | ✅           |
| Vero           | ✅           |
