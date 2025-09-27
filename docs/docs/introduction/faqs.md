# FAQs

??? question "Will my validators go offline if one of the connected beacon nodes goes offline?"

    Most of the time Vero can keep going even if only a single connected beacon node is online
    and synced. This means you can perform short maintenance on your nodes like applying
    client updates.

    Most of the time is not all the time though. Vero uses a threshold of beacon nodes
    at the start of every epoch to confirm finality checkpoints, in order not to
    follow an incorrect chain. This threshold defaults to a majority of beacon nodes (>50%)
    and can be overridden through a CLI argument.

??? question "Is Vero compatible with Dirk remote signers?"

    No. Dirk doesn't implement the
    [Ethereum Remote Signing API](https://github.com/ethereum/remote-signing-api){:target="_blank"}
    but uses a different API. Adding compatibility for Dirk remote signers
    is being considered. Let us know if this is something that would be interesting
    to you.

??? question "I notice Vero is written in Python. Should I be worried about performance?"

    The workload of a validator client is not particularly processing-heavy,
    therefore the choice of programming language does not play a great role
    when it comes to performance.

    Most of a validator client's work consists of asking other software for data:

      - beacon nodes - e.g. keeping track of validator duties
      - remote signer - signing validator duties

    And while Python may not be the fastest language, it has many advantages
    that make it the perfect choice for Vero:

    - Simplicity

        Being simple is one of Vero's [design goals](../index.md#design-goals).
        Python's readability and extensive standard library greatly contribute
        to keeping things simple.

    - Testability

        pytest is a popular Python testing framework. It is very powerful
        and allows developers to test various aspects of their software
        which is frequently much harder in other languages. This same framework
        is used by Ethereum teams to test the
        [consensus](https://github.com/ethereum/consensus-specs){:target="_blank"}
        and [execution](https://github.com/ethereum/execution-spec-tests){:target="_blank"}
        specs.

        A robust extensive test suite plays an important part in protecting Vero
        itself from bugs.

    At [Serenita](https://serenita.io){:target="_blank"}, we run thousands
    of Vero-powered validators and we frequently rank among the very
    [top performers](https://explorer.rated.network/leaderboard?network=mainnet&timeWindow=30d){:target="_blank"}.
