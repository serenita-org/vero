# Migrating to Vero

This guide will help you migrate your validators from other validator clients to Vero safely and efficiently.

---

## Pre-Migration Checklist

Migrating a validator client requires careful planning to avoid slashing risks. Before proceeding, complete the following checklist:

### :material-check-all: Safety Requirements

- [ ] **Verify no duplicate keys**: Ensure your validator keys are not running on any other machine or client. Running the same keys in multiple locations simultaneously will result in slashing.

- [ ] **Slashing protection database**: Ensure your remote signer has a functioning slashing protection database. Vero relies entirely on your remote signer's slashing protection—it does not maintain its own.

- [ ] **Downtime planning**: Plan for a brief period of downtime (typically 1-3 epochs) during the migration. While Vero offers [doppelganger detection](#doppelganger-detection), a short pause ensures safety.

- [ ] **Network synchronization**: Ensure all connected beacon nodes are fully synced before starting Vero.

- [ ] **Backup important data**: Back up any critical configuration files and validator metadata from your current setup.

### :material-server: Infrastructure Requirements

- [ ] **Remote signer deployed**: Vero requires a remote signer (e.g., Web3Signer) and does not manage keys directly. Ensure your remote signer is set up and contains your validator keys.

- [ ] **Multiple beacon nodes**: While Vero works with a single beacon node, the true benefits come from running multiple diverse clients. Prepare at least 2-3 different CL clients (e.g., Lighthouse + Lodestar + Nimbus).

- [ ] **Resource verification**: Confirm your hardware meets the combined resource requirements of Vero + remote signer + multiple beacon nodes.

### :material-information-outline: Information Gathering

- [ ] **Document current configuration**: Note your current client's flags, fee recipient, gas limit, graffiti, and any MEV relay configurations.

- [ ] **Identify validator count**: Know how many validators you'll be migrating.

- [ ] **Check current epoch**: Note the current epoch and plan your migration for a period of low activity if possible (though this is not strictly necessary).

---

## Migrating from Traditional Validator Clients

This section covers migrating from single-node validator clients like **Lighthouse**, **Prysm**, **Teku**, **Lodestar**, **Nimbus**, and **Grandine**.

### Architecture Differences

| Aspect | Traditional Clients | Vero |
|--------|---------------------|------|
| **Key management** | Built-in or local keystores | Requires remote signer (Web3Signer) |
| **Beacon node usage** | Single primary with optional fallback | Multi-node consensus by default |
| **Slashing protection** | Built-in database | Relies on remote signer |
| **Attestation safety** | Single source of truth | Cross-checked across multiple clients |

### Step-by-Step Migration

#### 1. Prepare Your Remote Signer

If you're not already using a remote signer, you'll need to set one up:

**Option A: Using eth-docker (Recommended for most users)**

Follow the [Setting up the remote signer](../quick-start/setting_up_remote_signer.md) guide for automated setup.

**Option B: Manual Web3Signer Setup**

```yaml
# Example docker-compose for Web3Signer
services:
  web3signer:
    image: consensys/web3signer:latest
    command:
      - --network=mainnet
      - --keystores-path=/keystores
      - --keystores-passwords-path=/passwords
      - --slashing-protection-db-url=jdbc:postgresql://postgres:5432/web3signer
      - --http-listen-host=0.0.0.0
      - --http-listen-port=9000
    volumes:
      - ./keystores:/keystores:ro
      - ./passwords:/passwords:ro
```

**Import your keys** into Web3Signer using its key import tools. The slashing protection database will preserve your signing history.

#### 2. Stop Your Current Validator Client

Gracefully stop your existing validator client. This is critical to avoid double-signing:

```bash
# Example: stopping a systemd service
sudo systemctl stop lighthouse-validator

# Or if using Docker
docker compose stop validator
```

Wait at least one full epoch (6.4 minutes on Ethereum mainnet) to ensure your old client has stopped all duties.

#### 3. Configure and Start Vero

Map your existing configuration to Vero's CLI arguments. See the [Configuration Mapping](#configuration-mapping) section below.

**Basic Docker example:**

```bash
docker run -d \
  --name vero \
  -p 8000:8000 \
  -p 8001:8001 \
  ghcr.io/serenita-org/vero:v1.2.0 \
  --network=mainnet \
  --remote-signer-url=http://web3signer:9000 \
  --beacon-node-urls=http://lighthouse:5052,http://lodestar:5052,http://nimbus:5052 \
  --fee-recipient=0xYourFeeRecipientAddress \
  --graffiti="Vero Validator"
```

#### 4. Verify the Migration

Check Vero's logs to confirm validators are active:

```bash
docker logs -f vero
```

You should see messages like:
```
INFO - Active validators detected - count: X
INFO - Validator duty completed - validator_index: X, slot: X, duty_type: Attestation
```

Monitor your validator performance on beacon chain explorers (e.g., beaconcha.in) to ensure attestations are being included.

---

## Migrating from Vouch

[Vouch](https://github.com/attestantio/vouch){:target="_blank"} is another multi-node validator client with similar goals to Vero. Migrating between them is straightforward since both use similar architecture patterns.

### Key Differences

| Feature | Vouch | Vero |
|---------|-------|------|
| **Written in** | Go | Python (with Rust extensions) |
| **Configuration** | YAML file-based | CLI flags |
| **Metrics format** | Prometheus | Prometheus |
| **Keymanager API** | Not supported | Supported |
| **MEV support** | Via mev-boost | Native with `--use-external-builder` |

### Migration Steps

#### 1. Document Your Vouch Configuration

Before stopping Vouch, note your configuration from `vouch.yml`:

```yaml
# Example Vouch configuration to document
accountmanager:
  distributed:
    url: http://dirk:8881

beaconnodeaddresses:
  - http://lighthouse:5052
  - http://prysm:5052
  - http://teku:5052

feerecipient:
  default: 0xYourFeeRecipientAddress
```

#### 2. Stop Vouch

```bash
# If running as systemd
sudo systemctl stop vouch

# If using Docker
docker stop vouch
```

#### 3. Adapt Your Configuration to Vero

Most Vouch settings translate directly to Vero CLI flags:

| Vouch Setting | Vero Equivalent |
|---------------|-----------------|
| `beaconnodeaddresses` | `--beacon-node-urls` |
| `feerecipient.default` | `--fee-recipient` |
| `feerecipient.validators` | Keymanager API per-validator setting |
| `graffiti` | `--graffiti` |
| `gaslimit` | `--gas-limit` |
| `controller.fast-track` | N/A (Vero always attempts fast attestation) |

#### 4. Start Vero

Since both Vero and Vouch use remote signers (Dirk for Vouch, Web3Signer for Vero), ensure your keys are accessible via Web3Signer:

```bash
docker run -d \
  --name vero \
  ghcr.io/serenita-org/vero:v1.2.0 \
  --network=mainnet \
  --remote-signer-url=http://web3signer:9000 \
  --beacon-node-urls=http://lighthouse:5052,http://prysm:5052,http://teku:5052 \
  --fee-recipient=0xYourFeeRecipientAddress \
  --attestation-consensus-threshold=2
```

---

## Configuration Mapping

### Common Flags Translated

#### From Lighthouse

| Lighthouse Flag | Vero Equivalent | Notes |
|-----------------|-----------------|-------|
| `--beacon-node` | `--beacon-node-urls` | Vero accepts multiple URLs |
| `--suggested-fee-recipient` | `--fee-recipient` | |
| `--graffiti` | `--graffiti` | |
| `--gas-limit` | `--gas-limit` | |
| `--http` | N/A | Vero's metrics/API are always enabled |
| `--http-address` | `--metrics-address`, `--keymanager-api-address` | Separate flags for each |
| `--http-port` | `--metrics-port`, `--keymanager-api-port` | Default 8000 for metrics, 8001 for Keymanager |
| `--enable-doppelganger-protection` | `--enable-doppelganger-detection` | |
| `--builder-proposals` | `--use-external-builder` | |
| `--builder-boost-factor` | `--builder-boost-factor` | |

#### From Prysm

| Prysm Flag | Vero Equivalent | Notes |
|------------|-----------------|-------|
| `--beacon-rpc-provider` | `--beacon-node-urls` | Use HTTP API port, not gRPC |
| `--suggested-fee-recipient` | `--fee-recipient` | |
| `--graffiti` | `--graffiti` | |
| `--enable-doppelganger` | `--enable-doppelganger-detection` | |
| `--validators-external-signer-url` | `--remote-signer-url` | |
| `--validators-proposer-blinded-blocks-enabled` | `--use-external-builder` | |
| `--validators-builder-boost-factor` | `--builder-boost-factor` | |

#### From Teku

| Teku Flag | Vero Equivalent | Notes |
|-----------|-----------------|-------|
| `--beacon-node-api-endpoint` | `--beacon-node-urls` | Vero accepts multiple URLs |
| `--validators-proposer-default-fee-recipient` | `--fee-recipient` | |
| `--validators-graffiti` | `--graffiti` | |
| `--validators-proposer-blinded-blocks-enabled` | `--use-external-builder` | |
| `--validators-builder-registration-default-enabled` | `--use-external-builder` | |
| `--validators-external-signer-url` | `--remote-signer-url` | |

#### From Vouch

| Vouch Setting | Vero Equivalent | Notes |
|---------------|-----------------|-------|
| `beaconnodeaddresses` | `--beacon-node-urls` | Comma-separated in Vero |
| `feerecipient.default` | `--fee-recipient` | |
| `feerecipient.validators` | Keymanager API | Set per-validator via API |
| `graffiti` | `--graffiti` | |
| `gaslimit` | `--gas-limit` | |

### Docker Compose Migration Example

**Before (Lighthouse Validator):**

```yaml
services:
  lighthouse-validator:
    image: sigp/lighthouse:latest
    command:
      - lighthouse
      - validator
      - --beacon-node=http://lighthouse-beacon:5052
      - --suggested-fee-recipient=0xYourAddress
      - --graffiti=LighthouseValidator
      - --enable-doppelganger-protection
    volumes:
      - ./validator-data:/root/.lighthouse
```

**After (Vero):**

```yaml
services:
  vero:
    image: ghcr.io/serenita-org/vero:v1.2.0
    command:
      - --network=mainnet
      - --remote-signer-url=http://web3signer:9000
      - --beacon-node-urls=http://lighthouse:5052,http://lodestar:5052,http://nimbus:5052
      - --fee-recipient=0xYourAddress
      - --graffiti=VeroValidator
      - --enable-doppelganger-detection
      - --metrics-address=0.0.0.0
    ports:
      - "8000:8000"
      - "8001:8001"
```

---

## Rolling Back

If you encounter issues with Vero, you can quickly roll back to your previous validator client.

### Quick Rollback Procedure

1. **Stop Vero:**
   ```bash
   docker stop vero
   # or
   sudo systemctl stop vero
   ```

2. **Wait one full epoch** (6.4 minutes on mainnet) to ensure no attestation or proposal duties are active.

3. **Restart your previous validator client** with its original configuration.

4. **Verify** your validators are attesting correctly via beacon chain explorers.

### Considerations When Rolling Back

- **Slashing protection**: Since Vero relies on your remote signer's slashing protection database, records of attestations and proposals made by Vero will be preserved. This prevents double-signing when switching back.

- **Doppelganger concerns**: If you start your old client immediately after stopping Vero (within the same slot), the network may detect doppelganger activity. Always wait at least a few slots, ideally a full epoch.

- **Configuration drift**: If you modified fee recipients, graffiti, or other settings via Vero's Keymanager API while running, ensure your old client's configuration reflects these changes before restarting.

---

## Doppelganger Detection

Vero supports optional doppelganger detection during startup, which can provide additional safety during migrations.

### How It Works

When `--enable-doppelganger-detection` is provided:

1. Vero pauses all validator duties for up to 3 epochs
2. Scans the network for any attestations or proposals from your validator keys
3. If activity is detected, Vero shuts down to prevent slashing
4. If no activity is detected, normal operations begin

### When to Use It

- :white_check_mark: **Recommended** when you're uncertain whether your old validator client has fully stopped
- :white_check_mark: **Recommended** when migrating keys that were previously used elsewhere
- :x: **Not necessary** if you've confirmed no other instances of your validators are running

### Limitations

!!! warning "Best-effort protection"

    Doppelganger detection is not foolproof. It cannot detect:
    
    - Validators that start signing after Vero's detection window
    - Network visibility issues where attestations aren't seen
    - Keys added via Keymanager API after startup

    Always verify your old client is stopped before starting Vero.

---

## Post-Migration Verification

After migrating, verify everything is working correctly:

### :material-check-circle: Immediate Checks (First 15 minutes)

- [ ] Vero logs show no errors
- [ ] Validators are detected and marked as active
- [ ] First attestations are being published
- [ ] No slashing detection alerts

### :material-trending-up: Short-term Monitoring (First 24 hours)

- [ ] Attestation effectiveness >95%
- [ ] No missed attestations due to Vero errors
- [ ] Grafana dashboard (if configured) shows healthy metrics
- [ ] Block proposals (if scheduled) are successful

### :material-chart-line: Long-term Monitoring

- [ ] Attestation rate comparable to pre-migration performance
- [ ] No unexpected slashing detection triggers
- [ ] MEV rewards (if enabled) are being received

---

## Troubleshooting Common Issues

### "No active validators detected"

**Cause**: Keys not properly imported into remote signer or wrong URL.

**Solution**: Verify your `--remote-signer-url` and ensure Web3Signer has your keys loaded.

### "Not enough beacon nodes available"

**Cause**: Less than the required threshold of beacon nodes are responding.

**Solution**: Check beacon node connectivity with `curl http://beacon-node:5052/eth/v1/node/health`

### Slashing detection triggered

**Cause**: Vero detected your validators were slashed, or there's a database issue.

**Solution**: Immediately investigate. Check beacon chain explorers to confirm validator status. Do not restart until you understand the cause.

### High attestation latency

**Cause**: Beacon nodes are geographically distant or under heavy load.

**Solution**: Ensure beacon nodes are close to Vero (low latency). Consider reducing `--attestation-consensus-threshold` if running many diverse nodes.

---

## Getting Help

If you encounter issues during migration:

1. Check the [CLI Reference](../reference/cli_reference.md) for detailed flag documentation
2. Review the [FAQs](../introduction/faqs.md) for common questions
3. Join the [Serenita Discord](https://discord.gg/serenita){:target="_blank"} for community support
4. Open an issue on [GitHub](https://github.com/serenita-org/vero/issues){:target="_blank"}

---

!!! success "Migration Complete!"

    Once you've verified your validators are performing well, you've successfully migrated to Vero. Welcome to multi-node validation!
