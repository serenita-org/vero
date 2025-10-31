# Changelog

## Upcoming release

#### Features
- Wait for beacon nodes to become available while starting up
- Optimize finality checkpoint confirmation for low validator counts
- Default gas limit set to 60M for Ethereum mainnet
- Improve block proposal fee recipient handling
- Generate build provenance and SBOM attestations for Vero container images
- Track health of connected remote signers (`remote_signer_score` metric, similar to `beacon_node_score`)

#### Bugfixes
- Sync duties not being performed for exited validators

## v1.3.0-rc.0 { id="v1.3.0-rc.0" }

<small>September 25, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.3.0-rc.0){:target="_blank"}

#### Features
- Add support for the Fulu fork on the Holešky and Hoodi testnets

#### Bugfixes
- Incorrect Keymanager API token length

## v1.2.0 { id="v1.2.0" }

<small>August 11, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.2.0){:target="_blank"}

#### Features
- Add doppelganger detection on launch using `--enable-doppelganger-detection`
- Attestation consensus optimizations
- Store a limited amount of debug logs in Vero's data directory
- Default gas limit set to 45M for Ethereum mainnet
- Default gas limit set to 60M for the Holešky and Hoodi testnets
- Set default for graffiti value to `Vero <version>`

## v1.2.0-rc.0 { id="v1.2.0-rc.0" }

<small>August 1, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.2.0-rc.0){:target="_blank"}

#### Features
- Add doppelganger detection on launch using `--enable-doppelganger-detection`
- Attestation consensus optimizations
- Store a limited amount of debug logs in Vero's data directory
- Default gas limit set to 45M for Ethereum mainnet
- Default gas limit set to 60M for the Holešky and Hoodi testnets

## v1.1.3 { id="v1.1.3" }

<small>July 9, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.1.3){:target="_blank"}

#### Bugfixes
- Incorrect serialization of a block attribute leads to the block
  being refused by Nimbus and Prysm beacon nodes

## v1.1.2 { id="v1.1.2" }

<small>June 16, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.1.2){:target="_blank"}

#### Features
- Remove some spurious and unnecessary log messages

## v1.1.1 { id="v1.1.1" }

<small>June 4, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.1.1){:target="_blank"}

#### Features
- Default gas limit set to 60M for the Holešky testnet and Ethereum mainnet

#### Bugfixes
- Incorrect attester duty updating retry logic while remote signer is unavailable

## v1.1.0 { id="v1.1.0" }

<small>May 19, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.1.0){:target="_blank"}

#### Features
- Introduce support for the Keymanager API, enabling per-validator overrides for
  fee recipient, graffiti and gas limit values

## v1.1.0-rc.0 { id="v1.1.0-rc.0" }

<small>May 13, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.1.0-rc.0){:target="_blank"}

#### Features
- Introduce support for the Keymanager API, enabling per-validator overrides for
  fee recipient, graffiti and gas limit values

## v1.0.0 { id="v1.0.0" }

<small>April 21, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.0.0){:target="_blank"}

#### Features
- Add support for the Electra fork on Ethereum and Gnosis Chain
- Add support for the Electra fork on the Holešky, Hoodi and Chiado testnets
- Add `----DANGER----disable-slashing-detection` CLI flag
- Default gas limit set to 36M for Ethereum mainnet
- Add a warning message for late head events

## v1.0.0-rc.2 { id="v1.0.0-rc.2" }

<small>March 16, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.0.0-rc.2){:target="_blank"}

#### Features
- Add support for the Electra fork on the Hoodi and Chiado testnets
- Add `----DANGER----disable-slashing-detection` CLI flag

## v1.0.0-rc.1 { id="v1.0.0-rc.1" }

<small>February 14, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.0.0-rc.1){:target="_blank"}

#### Bugfixes
- Incorrect pre-Electra aggregate requests

## v1.0.0-rc.0 { id="v1.0.0-rc.0" }

<small>February 13, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v1.0.0-rc.0){:target="_blank"}

#### Features
- Add support for the Electra fork on the Holešky testnet

## v0.9.1 { id="v0.9.1" }

<small>February 1, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v0.9.1){:target="_blank"}

#### Features
- Add `--network-custom-config-path` CLI argument
- Default gas limit set to 36M for Ethereum mainnet

## v0.9.0 { id="v0.9.0" }

<small>January 20, 2025</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v0.9.0){:target="_blank"}

#### Breaking changes
- Add mandatory `--network` CLI argument

#### Features
- Add per-network gas limit defaults
- Default gas limit set to 36M for the Holešky testnet
- Improvements in shutdown handling
- Track attestation consensus contributions
- Track the value of blocks produced by connected beacon nodes

Metrics            |  Trace Data
:-------------------------:|:-------------------------:
<img width="748" alt="image" src="https://github.com/user-attachments/assets/1d5b0fa0-63fd-4de8-88e2-70ccec307950" />  |  <img width="773" alt="image" src="https://github.com/user-attachments/assets/78c8ed32-70f9-448e-ae2e-90973fcb5559" />

## v0.8.3 { id="v0.8.3" }

<small>October 16, 2024</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v0.8.3){:target="_blank"}

#### Bugfixes
- Incorrect value of the `vc_attestation_consensus_failures` metric

## v0.8.2 { id="v0.8.2" }

<small>September 24, 2024</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v0.8.2){:target="_blank"}

#### Features
- Various performance optimizations in attestation and aggregation duties

## v0.8.1 { id="v0.8.1" }

<small>September 5, 2024</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v0.8.1){:target="_blank"}

#### Features
- Attestation aggregation optimization for high validator counts

#### Bugfixes
- Incorrect beacon node in use when one of them goes offline

## v0.8.0 { id="v0.8.0" }

<small>August 24, 2024</small>&nbsp;&nbsp;&nbsp;[:octicons-mark-github-16: GitHub Release](https://github.com/serenita-org/vero/releases/tag/v0.8.0){:target="_blank"}

The first public release of Vero.

#### Features
- Supports Ethereum and Gnosis Chain at the Deneb fork
- Supports all validator duties
- Fully compatible with all CL and EL clients
- Includes support for externally built blocks (mev-boost)
