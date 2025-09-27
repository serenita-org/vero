# Risks

## Slashing Risk

Vero can only be used in combination with a remote signer.

The remote signer and its battle-tested slashing protection
database prevent your validators from committing
a slashable offense no matter what data Vero requests to
sign.

As long as your validator keys are only active in one place,
using Vero does not increase your risk of slashing.
Even better, Vero can actually decrease slashing risk
through its proactive
[slashing protection measures](../reference/slashing_protection.md).

## Key Security

Vero never has direct access to validator private keys.
It can only request the remote signer to sign data
using those keys, which the remote signer will refuse
if the data to-be-signed would result in a slashable offense.

## Bugs

Vero's surface area for bugs is limited thanks to
the small size of its own codebase, a
[very small set of external dependencies](https://github.com/serenita-org/vero/blob/master/pyproject.toml){:target="_blank"}
and high test coverage.

Vero is also regularly tested against all open-source
beacon node implementations to check for any
incompatibilities using
[ethereum-package](https://github.com/ethpandaops/ethereum-package){:target="_blank"}.

## Vendor Lock-in

Switching to Vouch or DVT is time-consuming and complicated,
and there is no quick or easy way to switch back should
something go wrong with those.

In comparison with the above, switching to —and back from—
Vero is much easier.
If you're already using a remote signer (Web3Signer),
you can switch between your current validator client and Vero
in minutes!
