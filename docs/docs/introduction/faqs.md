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

    A validator client's workload is not computationally intensive, so the
    choice of programming language has little impact on performance.

    Most of what a validator client does is simply requesting data
    from other software components:

      - beacon nodes - e.g. tracking validator duties
      - remote signer - signing those duties

    Python was chosen because it has many strengths that make it an excellent fit for Vero:

    - **Simplicity**

        Simplicity is one of Vero's [design goals](../index.md#design-goals).
        Python's readability and extensive standard library greatly contribute
        to keeping things simple and bug-free.

    - **Testability**

        [pytest](https://pytest.org/){:target="_blank"}
        is a powerful and widely used testing framework
        that we use to test Vero.

        The same framework is also used by Ethereum teams to test the
        [consensus](https://github.com/ethereum/consensus-specs){:target="_blank"}
        and [execution](https://github.com/ethereum/execution-spec-tests){:target="_blank"}
        specs.

        A comprehensive test suite plays an important part
        in preventing bugs in Vero itself.

    - **Performance**

        Wait, what? That's right. In areas where raw speed matters,
        we use libraries written in highly efficient languages like C or Rust.
        This approach lets us combine Python’s simplicity with the speed of
        lower-level languages, giving us the best of both worlds.

    At [Serenita](https://serenita.io){:target="_blank"}, we operate thousands
    of Vero-powered, bug-resistant validators, and we frequently rank among the
    [best‑performing](https://explorer.rated.network/leaderboard?network=mainnet&timeWindow=30d){:target="_blank"}
    staking node operators.
