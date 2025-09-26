# FAQs

??? question "Will my validators go offline if one of the connected beacon nodes goes offline?"

    Vero can keep running for some amount of time even if only a single connected beacon node
    is online and synced. This allows short maintenance tasks, such as applying client updates,
    without downtime.

    Vero only requires a threshold of beacon nodes to be online at the start of each epoch,
    in order to verify the finality checkpoints being voted on.

??? question "Is Vero compatible with Dirk remote signers?"

    No. Dirk does not implement the
    [Ethereum Remote Signing API](https://github.com/ethereum/remote-signing-api){:target="_blank"}
    and instead uses a different API. Compatibility for Dirk remote signers is under consideration.
    Let us know if this is something that would be interesting to you.

??? question "I notice Vero is written in Python. Should I be worried about performance?"

    A validator client's workload is not particularly processing-heavy, so the
    choice of programming language has little impact on performance.

    Most of a validator client's work consists of asking other software
    for data:

      - beacon nodes - e.g. keeping track of validator duties
      - remote signer - signing validator duties

    Python has many strengths that make it the perfect choice for Vero:

    - Simplicity

        Being simple is one of Vero's [design goals](../index.md#design-goals).
        Python's readability and extensive standard library greatly contribute
        to keeping things simple.

    - Testability

        [pytest](https://pytest.org/){:target="_blank"}
        is a powerful and popular Python testing framework
        that we use to test Vero. It makes testing various
        aspects of software much easier than testing
        frameworks for other languages.

        This same framework
        is used by Ethereum teams to test the
        [consensus](https://github.com/ethereum/consensus-specs){:target="_blank"}
        and [execution](https://github.com/ethereum/execution-spec-tests){:target="_blank"}
        specs.

        A robust and extensive test suite plays an important part
        in protecting against bugs in Vero itself.

    At [Serenita](https://serenita.io){:target="_blank"}, we run thousands
    of Vero-powered validators and we frequently rank among the
    [best‑performing](https://explorer.rated.network/leaderboard?network=mainnet&timeWindow=30d){:target="_blank"}
    staking node operators.
