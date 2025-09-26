# Risks

## Slashing Risk

Vero can only be used in combination with a remote signer.

The remote signer, with its battle-tested slashing protection
database, prevents your validators from committing a slashable
offense – no matter what data Vero requests to sign.

As long as your validator keys are active in only one place,
Vero does not increase your slashing risk.
Even better, Vero can actually decrease slashing risk
through its proactive
[slashing protection measures](../reference/slashing_protection.md).

## Key Security

Vero never has direct access to validator private keys.
It can only request the remote signer to sign data
using those keys, which the remote signer will refuse
if the data to be signed would result in a slashable offense.

## Bugs

Vero's bug surface area is limited thanks to
its small codebase, a
[minimal set of external dependencies](https://github.com/serenita-org/vero/blob/master/pyproject.toml){:target="_blank"},
and high test coverage.

Vero is also regularly tested against all open-source
beacon node implementations to ensure compatibilty using
[ethereum-package](https://github.com/ethpandaops/ethereum-package){:target="_blank"}.

## Vendor Lock-in

Switching to Vouch or DVT is time‑consuming and
complicated – and switching back is equally difficult
if something were to go wrong with those.

By contrast, switching to —and back from—
Vero is much easier.
If you're already using a remote signer (Web3Signer),
you can switch between your current validator client and Vero
in just minutes.
