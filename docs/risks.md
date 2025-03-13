# Risks

- ### Slashing risk

Vero can only be used in combination with a remote signer.

The remote signer and its battle-tested slashing protection
database prevent your validators from committing
a slashable offense no matter what data Vero requests to
sign.

- ### Validator keys

Vero never has direct access to validator private keys.
It can only request the remote signer to sign data
using those keys, which the remote signer will refuse
if the data to-be-signed could result in a slashable offense.

- ### Bugs

Vero's surface area for bugs is limited thanks to
the small size of its own codebase and a [very small set
of external dependencies](../pyproject.toml)
and high test coverage.

Vero is also regularly tested against all
open-source beacon node implementations
to check for any incompatibilities
using
[ethereum-package](https://github.com/ethpandaops/ethereum-package).

- ### Lock-in

Switching to Vouch or DVT is quite time-consuming,
and there is no quick or easy way to switch back should
something go wrong with those.

The cost of switching to and back from Vero is very low.
If you're already using a remote signer, it can be done
in minutes.

- ### Downtime

Admittedly, **the biggest risk of using Vero is downtime**.
While Vero has been running on devnets, testnets and
live mainnet networks for several months, it is not as
battle-tested as other validator clients.

It is, however, easy to switch to other validator client
implementations in case an issue does occur.
