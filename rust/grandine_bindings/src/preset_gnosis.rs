//! Gnosis preset for the `grandine_bindings` library.
//!
//! Based on the Gnosis Chain consensus specs:
//! `<https://github.com/gnosischain/specs>`
//!
//! Key differences from Mainnet:
//! - `BASE_REWARD_FACTOR`: 25 (Mainnet: 64)
//! - `SLOTS_PER_EPOCH`: 16 (Mainnet: 32)
//! - `EPOCHS_PER_SYNC_COMMITTEE_PERIOD`: 512 (Mainnet: 256)
//! - `MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP`: 8192 (Mainnet: 16384)
//! - `MAX_WITHDRAWALS_PER_PAYLOAD`: 8 (Mainnet: 16)
//! - `MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP`: 6 (Mainnet: 8)

use grandine_types::phase0::primitives::Gwei;
use grandine_types::preset::{Preset, PresetName};
use std::num::NonZeroU64;
use typenum::{
    Prod, Quot, U1, U1048576, U1073741824, U1099511627776, U128, U134217728, U16, U16777216, U17,
    U2, U2048, U256, U262144, U32, U4, U4096, U512, U64, U65536, U8, U8192,
};

/// [Gnosis preset](https://github.com/gnosischain/specs).
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Default, Debug)]
pub struct Gnosis;

impl Preset for Gnosis {
    // Phase 0 - Different from Mainnet
    type EpochsPerEth1VotingPeriod = U64;
    type EpochsPerHistoricalRoot = U512;
    type EpochsPerHistoricalVector = U65536;
    type EpochsPerSlashingsVector = U8192;
    type HistoricalRootsLimit = U16777216;
    type MaxAttestations = U128;
    type MaxAttesterSlashings = U2;
    type MaxCommitteesPerSlot = U64;
    type MaxDeposits = U16;
    type MaxProposerSlashings = U16;
    type MaxValidatorsPerCommittee = U2048;
    type MaxVoluntaryExits = U16;
    type MinSeedLookahead = U1;
    // Gnosis: 16, Mainnet: 32
    type SlotsPerEpoch = U16;
    type ValidatorRegistryLimit = U1099511627776;

    // Altair - Same as Mainnet
    type SyncCommitteeSize = U512;

    // Bellatrix - Same as Mainnet
    type BytesPerLogsBloom = U256;
    type MaxBytesPerTransaction = U1073741824;
    type MaxExtraDataBytes = U32;
    type MaxTransactionsPerPayload = U1048576;

    // Capella - Different from Mainnet
    type MaxBlsToExecutionChanges = U16;
    // Gnosis: 8, Mainnet: 16
    type MaxWithdrawalsPerPayload = U8;

    // Deneb - Same as Mainnet
    type FieldElementsPerBlob = U4096;
    type MaxBlobCommitmentsPerBlock = U4096;
    type KzgCommitmentInclusionProofDepth = U17;

    // Electra - Same as Mainnet
    type MaxAttestationsElectra = U8;
    type MaxAttesterSlashingsElectra = U1;
    type MaxConsolidationRequestsPerPayload = U2;
    type MaxDepositRequestsPerPayload = U8192;
    type MaxWithdrawalRequestsPerPayload = U16;
    type PendingDepositsLimit = U134217728;
    type PendingConsolidationsLimit = U262144;
    type PendingPartialWithdrawalsLimit = U134217728;

    // Fulu - Same as Mainnet
    type FieldElementsPerCell = U64;
    type KzgCommitmentsInclusionProofDepth = U4;
    type FieldElementsPerExtBlob = U8192;
    type NumberOfColumns = U128;

    // Derived type-level variables
    type MaxAttestersPerSlot = Prod<Self::MaxValidatorsPerCommittee, Self::MaxCommitteesPerSlot>;
    type MaxCellProofsPerBlock =
        Prod<Self::FieldElementsPerExtBlob, Self::MaxBlobCommitmentsPerBlock>;
    type CellsPerExtBlob = Quot<Self::FieldElementsPerExtBlob, Self::FieldElementsPerCell>;

    // Meta - Note: NAME is only used internally for preset identification
    // Since Gnosis is not in upstream Grandine, we use Mainnet as base
    // but this implementation provides the correct Gnosis-specific values
    const NAME: PresetName = PresetName::Mainnet;

    // Phase 0 - Different from Mainnet
    // Gnosis: 25, Mainnet: 64
    const BASE_REWARD_FACTOR: u64 = 25;
    const EFFECTIVE_BALANCE_INCREMENT: NonZeroU64 = NonZeroU64::new(1_000_000_000).unwrap();
    const HYSTERESIS_DOWNWARD_MULTIPLIER: u64 = 1;
    const HYSTERESIS_QUOTIENT: NonZeroU64 = NonZeroU64::new(4).unwrap();
    const HYSTERESIS_UPWARD_MULTIPLIER: u64 = 5;
    const INACTIVITY_PENALTY_QUOTIENT: NonZeroU64 = NonZeroU64::new(1_u64 << 26).unwrap();
    const MAX_EFFECTIVE_BALANCE: Gwei = 32_000_000_000;
    const MAX_SEED_LOOKAHEAD: u64 = 4;
    const MIN_ATTESTATION_INCLUSION_DELAY: NonZeroU64 = NonZeroU64::new(1).unwrap();
    const MIN_DEPOSIT_AMOUNT: Gwei = 1_000_000_000;
    const MIN_EPOCHS_TO_INACTIVITY_PENALTY: u64 = 4;
    const MIN_SLASHING_PENALTY_QUOTIENT: NonZeroU64 = NonZeroU64::new(128).unwrap();
    const PROPORTIONAL_SLASHING_MULTIPLIER: u64 = 1;
    const PROPOSER_REWARD_QUOTIENT: NonZeroU64 = NonZeroU64::new(8).unwrap();
    const SHUFFLE_ROUND_COUNT: u8 = 90;
    const TARGET_COMMITTEE_SIZE: NonZeroU64 = NonZeroU64::new(128).unwrap();
    const WHISTLEBLOWER_REWARD_QUOTIENT: NonZeroU64 = NonZeroU64::new(512).unwrap();

    // Altair - Different from Mainnet
    // Gnosis: 512, Mainnet: 256
    const EPOCHS_PER_SYNC_COMMITTEE_PERIOD: NonZeroU64 = NonZeroU64::new(512).unwrap();
    const INACTIVITY_PENALTY_QUOTIENT_ALTAIR: NonZeroU64 = NonZeroU64::new(3_u64 << 24).unwrap();
    const MIN_SLASHING_PENALTY_QUOTIENT_ALTAIR: NonZeroU64 = NonZeroU64::new(64).unwrap();
    const MIN_SYNC_COMMITTEE_PARTICIPANTS: usize = 1;
    const PROPORTIONAL_SLASHING_MULTIPLIER_ALTAIR: u64 = 2;

    // Bellatrix - Same as Mainnet
    const INACTIVITY_PENALTY_QUOTIENT_BELLATRIX: NonZeroU64 = NonZeroU64::new(1_u64 << 24).unwrap();
    const MIN_SLASHING_PENALTY_QUOTIENT_BELLATRIX: NonZeroU64 = NonZeroU64::new(32).unwrap();
    const PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX: u64 = 3;

    // Capella - Different from Mainnet
    // Gnosis: 8192, Mainnet: 16384
    const MAX_VALIDATORS_PER_WITHDRAWALS_SWEEP: u64 = 1 << 13;

    // Electra - Different from Mainnet
    const MAX_EFFECTIVE_BALANCE_ELECTRA: Gwei = 2_048_000_000_000;
    // Gnosis: 6, Mainnet: 8
    const MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP: u64 = 6;
    const MAX_PENDING_DEPOSITS_PER_EPOCH: u64 = 16;
    const MIN_ACTIVATION_BALANCE: Gwei = 32_000_000_000;
    const MIN_SLASHING_PENALTY_QUOTIENT_ELECTRA: NonZeroU64 = NonZeroU64::new(4096).unwrap();
    const WHISTLEBLOWER_REWARD_QUOTIENT_ELECTRA: NonZeroU64 = NonZeroU64::new(4096).unwrap();
}
