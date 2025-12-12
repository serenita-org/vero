# Vero

**Vero** is a multi-node validator client designed to
**protect validators from client bugs**. It does this by cross-checking
the blockchain state across multiple client implementations
before submitting attestations.

Vero works on both **Ethereum** and **Gnosis Chain**,
and is compatible with all CL and EL clients.

## Documentation

Docs are available at [vero.docs.serenita.io](https://vero.docs.serenita.io).

## Contributing

Contributions are welcome!
See [CONTRIBUTING.md](./CONTRIBUTING.md) for more details.

## Resources

A selection of talks, articles, and community resources for learning more about Vero:

- Guides
  - [Eth Docker: Running Vero with three client pairs](https://ethdocker.com/Usage/Advanced/Vero)
- Presentations
  - [EthClient Summit 2025: When Clients Disagree: Picking a Side Safely](https://www.youtube.com/watch?v=49uGX8j7Tqw)
  - [EthStaker's Staking Gathering 2025: Improving Ethereum's Resilience With Multi-node Validator Setups](https://www.youtube.com/watch?v=cGqgtzBsFGQ)
  - [EthCC 2025: Improving client diversity with Vero](https://www.youtube.com/watch?v=eKE9-XpTuBo)
  - [Lido Node Operator Community Call #22: Improving Client Diversity with Vero](https://youtu.be/JswJdjUCNgs?list=PLhvXP1-8VKZQnuhrHrBBe5asNIoBSJkDv&t=2525)
  - [EthStaker's Community Call #56: Vero](https://www.youtube.com/watch?v=h2GlNXka6og)
- Questions
  - [Telegram](https://t.me/+2Sr84lqsuOU0NjQ0)
  - Discord (invite-only)
- Workshops
  - [Dappcon 2025: Protecting Validators From Client Bugs Using Vero](https://www.youtube.com/watch?v=afxfNc6Gf7Y)


## Acknowledgements

We'd like to acknowledge the work of all teams that helped shape Vero, including:

- Ethereum and Gnosis Chain client teams, researchers and everyone else
  working on these public goods
- [@protolambda](https://github.com/protolambda) and his [Python SSZ implementation](https://github.com/protolambda/remerkleable)
- [Kurtosis](https://github.com/kurtosis-tech/kurtosis)
  and their contributions to
  [ethereum-package](https://github.com/ethpandaops/ethereum-package)
- The EF DevOps team and their continued work on amazing tooling like
  [ethereum-package](https://github.com/ethpandaops/ethereum-package)
  which helped thoroughly test Vero before launching it on testnet
