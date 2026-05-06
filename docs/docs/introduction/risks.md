# Risks

Various risks inherently exist in the design space of
a validator client. That said, Vero was designed to minimize operational,
security, and slashing risk wherever possible.

Vero also underwent an
[independent security review](https://github.com/sigp/public-audits/tree/master/reports/serenita-vero){:target="_blank"}
conducted by Sigma Prime in early 2026.

## Slashing Risk

Vero can only be used in combination with a remote signer.

The remote signer, with its battle-tested slashing protection
database, prevents validators from committing a slashable
offense – no matter what data Vero requests to sign.

As long as your validator keys are active in only one place,
Vero does not increase your slashing risk.
Even better, Vero can actually decrease slashing risk
through its proactive
[slashing protection measures](../reference/slashing_protection.md).

## Key Security

By design, Vero **never** has direct access to validator private keys.

## Bugs

Vero's bug surface area is limited thanks to
its small codebase, a
[minimal set of external dependencies](https://github.com/serenita-org/vero/blob/master/pyproject.toml){:target="_blank"},
and high test coverage.

Vero is also regularly tested against all open-source
beacon node implementations to ensure compatibility using
[ethereum-package](https://github.com/ethpandaops/ethereum-package){:target="_blank"}.

## Vendor Lock-in

Switching to Vouch or DVT is time‑consuming and
complicated – and switching back is equally difficult
if something were to go wrong with those.

By contrast, switching to —and back from—
Vero is straightforward.
If you are already using a remote signer such as Web3Signer,
you can switch between your current validator client and Vero
within minutes.
