# Slashing protection

## Prevention

### Slashing Protection Database

Vero relies on the battle-tested slashing protection
measures of the attached remote signer, similar to Vouch.
Another layer of slashing protection may be added directly
to Vero in the future.

### Doppelganger Detection

Vero supports detecting active doppelganger validators on
the network during its startup. Doppelgangers are identical
validators that are running elsewhere. Running identical
validators in multiple locations can lead to the validators
getting slashed due to emitting conflicting votes.

If Vero detects active doppelgangers on the network, it will
not start performing validator duties and will shut down
instead.

## Slashing Event Detection

Vero closely monitors and attempts to detect validator
slashing events as quickly as possible
and **stops performing all duties for all of its
validators whenever it detects any of them have
been slashed**. This may sound excessive but we
believe any slashing event should be thoroughly
investigated before resuming duties. A slashing
event should never occur in a well-setup environment,
therefore if such an event does occur, it indicates
a larger issue.

Vero detects slashing events in 2 ways:

- it listens to slashing events emitted by
connected beacon nodes in its event stream
	- This is one of the fastest ways to detect
      a slashing event and ensures Vero reacts
      to these as quickly as possible.

- it regularly polls the status of all validators
	- This is a fallback mechanism in case the beacon
      node does not emit a slashing event or Vero
      fails to process it.

A metric - `slashing_detected` - exposes the status of
the slashing detection mechanism and is also displayed
in the overview section of the Grafana dashboard:

![Metrics - overview](images/instrumentation/metrics_overview.png)
