# Slashing Protection

## Proactive Measures

- Slashing Protection Database

    Vero relies on the battle-tested slashing protection
    provided by the attached remote signer.
    An additional layer of slashing protection may be added
    directly to Vero in the future.

- Doppelganger Detection

    Vero supports detecting active doppelganger validators on
    the network during its startup. Doppelgangers are identical
    validators running elsewhere. Running the same
    validator in multiple locations can lead to slashing,
    as they may emit conflicting votes.

    If Vero detects active doppelgangers, it will refuse to
    start validator duties and shut down instead.

## Reactive Measures

- Slashing Event Detection

    Vero closely monitors validator slashing events
    happening on the network and **stops performing
    validator duties for all of its validators
    whenever it detects any of them have been
    slashed**. While strict, this helps ensure that slashing
    events get properly reviewed before duties are resumed.
    A slashing event should never occur in a properly configured
    environment, therefore, if such an event does occur,
    it indicates a larger issue.

    The `slashing_detected` metric exposes the status of
    the slashing detection mechanism and is also displayed
    in the overview section of the Grafana dashboard:

![Metrics - overview](assets/instrumentation/metrics_overview.png)
