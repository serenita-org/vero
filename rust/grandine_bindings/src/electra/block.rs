//! Electra block types for Python bindings.
//!
//! This module provides Python-exposed types for:
//! - `SignedBeaconBlock` (Mainnet, Minimal, Gnosis)
//! - `BeaconBlockContents` with KZG proofs and blobs (Mainnet, Minimal, Gnosis)
//! - `SignedBeaconBlockContents` (Mainnet, Minimal, Gnosis)
//! - `BlindedBeaconBlock` (Mainnet, Minimal, Gnosis)
//! - `SignedBlindedBeaconBlock` (Mainnet, Minimal, Gnosis)
//!
//! Each type supports SSZ and JSON serialization via `from_ssz`, `to_ssz`,
//! `from_json`, and `to_json` methods. Block contents and blinded blocks also
//! provide `header_dict`, `sign`, and `block_hash_tree_root` helper methods.

use paste::paste;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::Gnosis;
use grandine_bls::SignatureBytes;
use grandine_ssz::{ContiguousList, Ssz, SszHash, SszReadDefault};
use grandine_types::deneb::primitives::{Blob, KzgProof};
use grandine_types::electra::containers::{
    BeaconBlock, BlindedBeaconBlock, SignedBeaconBlock, SignedBlindedBeaconBlock,
};
use grandine_types::preset::{Mainnet, Minimal, Preset};
use serde::{Deserialize, Serialize};

// Bring the macro into scope (because it's #[macro_export], it's at crate root)
use crate::define_ssz_pyclass_for_preset;

// =============================================================================
// Helper traits and functions to reduce duplication between block types
// =============================================================================

use grandine_ssz::H256;

/// Trait for types that can provide beacon block header fields for signing.
///
/// This is implemented for both `BeaconBlock<P>` and `BlindedBeaconBlock<P>`,
/// allowing the `header_dict_impl` function to work with either block type.
pub trait BlockHeader {
    /// Returns the slot number of the block.
    fn slot(&self) -> u64;
    /// Returns the proposer validator index.
    fn proposer_index(&self) -> u64;
    /// Returns the parent block's root hash.
    fn parent_root(&self) -> &H256;
    /// Returns the state root hash.
    fn state_root(&self) -> &H256;
    /// Returns the body root hash.
    fn body_root(&self) -> H256;
}

impl<P: Preset> BlockHeader for BeaconBlock<P> {
    fn slot(&self) -> u64 {
        self.slot
    }
    fn proposer_index(&self) -> u64 {
        self.proposer_index
    }
    fn parent_root(&self) -> &H256 {
        &self.parent_root
    }
    fn state_root(&self) -> &H256 {
        &self.state_root
    }
    fn body_root(&self) -> H256 {
        self.body.hash_tree_root()
    }
}

impl<P: Preset> BlockHeader for BlindedBeaconBlock<P> {
    fn slot(&self) -> u64 {
        self.slot
    }
    fn proposer_index(&self) -> u64 {
        self.proposer_index
    }
    fn parent_root(&self) -> &H256 {
        &self.parent_root
    }
    fn state_root(&self) -> &H256 {
        &self.state_root
    }
    fn body_root(&self) -> H256 {
        self.body.hash_tree_root()
    }
}

/// Creates a Python dict containing beacon block header fields.
///
/// Returns a `PyDict` with keys: `slot`, `proposer_index`, `parent_root`,
/// `state_root`, and `body_root`. All hash values are hex-encoded with `0x` prefix.
fn header_dict_impl(
    header: &impl BlockHeader,
    py: Python<'_>,
) -> PyResult<Py<pyo3::types::PyDict>> {
    use pyo3::types::PyDict;

    let d = PyDict::new(py);
    d.set_item("slot", header.slot().to_string())?;
    d.set_item("proposer_index", header.proposer_index().to_string())?;
    d.set_item(
        "parent_root",
        format!("0x{}", hex::encode(header.parent_root().as_bytes())),
    )?;
    d.set_item(
        "state_root",
        format!("0x{}", hex::encode(header.state_root().as_bytes())),
    )?;
    d.set_item(
        "body_root",
        format!("0x{}", hex::encode(header.body_root().as_bytes())),
    )?;
    Ok(d.into())
}

/// Parses a hex-encoded BLS signature string.
///
/// # Errors
///
/// Returns `PyValueError` if the hex string is invalid or the signature bytes
/// cannot be decoded.
fn parse_signature(signature: &str) -> PyResult<SignatureBytes> {
    let signature_clean = signature.trim_start_matches("0x");
    let signature_bytes = hex::decode(signature_clean)
        .map_err(|e| PyValueError::new_err(format!("Invalid signature hex: {e}")))?;

    SignatureBytes::from_ssz_default(&signature_bytes)
        .map_err(|e| PyValueError::new_err(format!("Invalid signature bytes: {e:?}")))
}

/// Formats an H256 hash as a hex string with `0x` prefix.
fn format_hash_tree_root(root: &H256) -> String {
    format!("0x{}", hex::encode(root.as_bytes()))
}

/// Block contents including the beacon block, KZG proofs, and blobs.
///
/// This is used for the full block that includes blob data (Deneb/Electra).
#[derive(Clone, PartialEq, Eq, Debug, Deserialize, Serialize, Ssz)]
#[serde(bound = "")]
pub struct BeaconBlockContents<P: Preset> {
    pub block: BeaconBlock<P>,
    pub kzg_proofs: ContiguousList<KzgProof, P::MaxBlobCommitmentsPerBlock>,
    pub blobs: ContiguousList<Blob<P>, P::MaxBlobCommitmentsPerBlock>,
}

/// Signed block contents including the signed beacon block, KZG proofs, and blobs.
#[derive(Clone, PartialEq, Eq, Debug, Deserialize, Serialize, Ssz)]
#[serde(bound = "")]
pub struct SignedBeaconBlockContents<P: Preset> {
    pub signed_block: SignedBeaconBlock<P>,
    pub kzg_proofs: ContiguousList<KzgProof, P::MaxBlobCommitmentsPerBlock>,
    pub blobs: ContiguousList<Blob<P>, P::MaxBlobCommitmentsPerBlock>,
}

paste! {
    define_ssz_pyclass_for_preset!(
        [<PySignedBeaconBlockMainnet>],
        "ElectraSignedBeaconBlockMainnet",
        SignedBeaconBlock<Mainnet>
    );

    define_ssz_pyclass_for_preset!(
        [<PySignedBeaconBlockMinimal>],
        "ElectraSignedBeaconBlockMinimal",
        SignedBeaconBlock<Minimal>
    );

    define_ssz_pyclass_for_preset!(
        [<PySignedBeaconBlockGnosis>],
        "ElectraSignedBeaconBlockGnosis",
        SignedBeaconBlock<Gnosis>
    );

    define_ssz_pyclass_for_preset!(
        [<PyBeaconBlockContentsMainnet>],
        "ElectraBeaconBlockContentsMainnet",
        BeaconBlockContents<Mainnet>,
        extra_methods = {
            pub fn header_dict(
                &self,
                py: pyo3::Python<'_>,
            ) -> pyo3::PyResult<pyo3::Py<pyo3::types::PyDict>> {
                header_dict_impl(&self.inner.block, py)
            }

            pub fn sign(
                &self,
                signature: &str,
            ) -> pyo3::PyResult<[<PySignedBeaconBlockContentsMainnet>]> {
                let signature = parse_signature(signature)?;

                let signed = SignedBeaconBlockContents::<Mainnet> {
                    signed_block: SignedBeaconBlock::<Mainnet> {
                        message: self.inner.block.clone(),
                        signature,
                    },
                    kzg_proofs: self.inner.kzg_proofs.clone(),
                    blobs: self.inner.blobs.clone(),
                };

                Ok([<PySignedBeaconBlockContentsMainnet>] { inner: signed })
            }

            pub fn block_hash_tree_root(&self) -> String {
                format_hash_tree_root(&self.inner.block.hash_tree_root())
            }
        }
    );

    define_ssz_pyclass_for_preset!(
        [<PyBeaconBlockContentsGnosis>],
        "ElectraBeaconBlockContentsGnosis",
        BeaconBlockContents<Gnosis>,
        extra_methods = {
            pub fn header_dict(
                &self,
                py: pyo3::Python<'_>,
            ) -> pyo3::PyResult<pyo3::Py<pyo3::types::PyDict>> {
                header_dict_impl(&self.inner.block, py)
            }

            pub fn sign(
                &self,
                signature: &str,
            ) -> pyo3::PyResult<[<PySignedBeaconBlockContentsGnosis>]> {
                let signature = parse_signature(signature)?;

                let signed = SignedBeaconBlockContents::<Gnosis> {
                    signed_block: SignedBeaconBlock::<Gnosis> {
                        message: self.inner.block.clone(),
                        signature,
                    },
                    kzg_proofs: self.inner.kzg_proofs.clone(),
                    blobs: self.inner.blobs.clone(),
                };

                Ok([<PySignedBeaconBlockContentsGnosis>] { inner: signed })
            }

            pub fn block_hash_tree_root(&self) -> String {
                format_hash_tree_root(&self.inner.block.hash_tree_root())
            }
        }
    );

    define_ssz_pyclass_for_preset!(
        [<PyBeaconBlockContentsMinimal>],
        "ElectraBeaconBlockContentsMinimal",
        BeaconBlockContents<Minimal>,
        extra_methods = {
            pub fn header_dict(
                &self,
                py: pyo3::Python<'_>,
            ) -> pyo3::PyResult<pyo3::Py<pyo3::types::PyDict>> {
                header_dict_impl(&self.inner.block, py)
            }

            pub fn sign(
                &self,
                signature: &str,
            ) -> pyo3::PyResult<[<PySignedBeaconBlockContentsMinimal>]> {
                let signature = parse_signature(signature)?;

                let signed = SignedBeaconBlockContents::<Minimal> {
                    signed_block: SignedBeaconBlock::<Minimal> {
                        message: self.inner.block.clone(),
                        signature,
                    },
                    kzg_proofs: self.inner.kzg_proofs.clone(),
                    blobs: self.inner.blobs.clone(),
                };

                Ok([<PySignedBeaconBlockContentsMinimal>] { inner: signed })
            }

            pub fn block_hash_tree_root(&self) -> String {
                format_hash_tree_root(&self.inner.block.hash_tree_root())
            }
        }
    );

    define_ssz_pyclass_for_preset!(
        [<PySignedBeaconBlockContentsMainnet>],
        "ElectraSignedBeaconBlockContentsMainnet",
        SignedBeaconBlockContents<Mainnet>
    );

    define_ssz_pyclass_for_preset!(
        [<PySignedBeaconBlockContentsMinimal>],
        "ElectraSignedBeaconBlockContentsMinimal",
        SignedBeaconBlockContents<Minimal>
    );

    define_ssz_pyclass_for_preset!(
        [<PySignedBeaconBlockContentsGnosis>],
        "ElectraSignedBeaconBlockContentsGnosis",
        SignedBeaconBlockContents<Gnosis>
    );

    define_ssz_pyclass_for_preset!(
        [<PyBlindedBeaconBlockMainnet>],
        "ElectraBlindedBeaconBlockMainnet",
        BlindedBeaconBlock<Mainnet>,
        extra_methods = {
            pub fn header_dict(
                &self,
                py: pyo3::Python<'_>,
            ) -> pyo3::PyResult<pyo3::Py<pyo3::types::PyDict>> {
                header_dict_impl(&self.inner, py)
            }

            pub fn sign(
                &self,
                signature: &str,
            ) -> pyo3::PyResult<[<PySignedBlindedBeaconBlockMainnet>]> {
                let signature = parse_signature(signature)?;

                let signed = SignedBlindedBeaconBlock::<Mainnet> {
                    message: self.inner.clone(),
                    signature,
                };

                Ok([<PySignedBlindedBeaconBlockMainnet>] { inner: signed })
            }

            pub fn block_hash_tree_root(&self) -> String {
                format_hash_tree_root(&self.inner.hash_tree_root())
            }
        }
    );

    define_ssz_pyclass_for_preset!(
        [<PyBlindedBeaconBlockGnosis>],
        "ElectraBlindedBeaconBlockGnosis",
        BlindedBeaconBlock<Gnosis>,
        extra_methods = {
            pub fn header_dict(
                &self,
                py: pyo3::Python<'_>,
            ) -> pyo3::PyResult<pyo3::Py<pyo3::types::PyDict>> {
                header_dict_impl(&self.inner, py)
            }

            pub fn sign(
                &self,
                signature: &str,
            ) -> pyo3::PyResult<[<PySignedBlindedBeaconBlockGnosis>]> {
                let signature = parse_signature(signature)?;

                let signed = SignedBlindedBeaconBlock::<Gnosis> {
                    message: self.inner.clone(),
                    signature,
                };

                Ok([<PySignedBlindedBeaconBlockGnosis>] { inner: signed })
            }

            pub fn block_hash_tree_root(&self) -> String {
                format_hash_tree_root(&self.inner.hash_tree_root())
            }
        }
    );

    define_ssz_pyclass_for_preset!(
        [<PyBlindedBeaconBlockMinimal>],
        "ElectraBlindedBeaconBlockMinimal",
        BlindedBeaconBlock<Minimal>,
        extra_methods = {
            pub fn header_dict(
                &self,
                py: pyo3::Python<'_>,
            ) -> pyo3::PyResult<pyo3::Py<pyo3::types::PyDict>> {
                header_dict_impl(&self.inner, py)
            }

            pub fn sign(
                &self,
                signature: &str,
            ) -> pyo3::PyResult<[<PySignedBlindedBeaconBlockMinimal>]> {
                let signature = parse_signature(signature)?;

                let signed = SignedBlindedBeaconBlock::<Minimal> {
                    message: self.inner.clone(),
                    signature,
                };

                Ok([<PySignedBlindedBeaconBlockMinimal>] { inner: signed })
            }

            pub fn block_hash_tree_root(&self) -> String {
                format_hash_tree_root(&self.inner.hash_tree_root())
            }
        }
    );
    define_ssz_pyclass_for_preset!(
        [<PySignedBlindedBeaconBlockMainnet>],
        "ElectraSignedBlindedBeaconBlockMainnet",
        SignedBlindedBeaconBlock<Mainnet>
    );
    define_ssz_pyclass_for_preset!(
        [<PySignedBlindedBeaconBlockMinimal>],
        "ElectraSignedBlindedBeaconBlockMinimal",
        SignedBlindedBeaconBlock<Minimal>
    );

    define_ssz_pyclass_for_preset!(
        [<PySignedBlindedBeaconBlockGnosis>],
        "ElectraSignedBlindedBeaconBlockGnosis",
        SignedBlindedBeaconBlock<Gnosis>
    );
}

/// Registers all Electra block types with the Python module.
///
/// # Errors
///
/// Returns `PyErr` if class registration fails.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Mainnet classes
    m.add_class::<PySignedBeaconBlockMainnet>()?;
    m.add_class::<PyBeaconBlockContentsMainnet>()?;
    m.add_class::<PySignedBeaconBlockContentsMainnet>()?;
    m.add_class::<PyBlindedBeaconBlockMainnet>()?;
    m.add_class::<PySignedBlindedBeaconBlockMainnet>()?;

    // Minimal classes
    m.add_class::<PySignedBeaconBlockMinimal>()?;
    m.add_class::<PyBeaconBlockContentsMinimal>()?;
    m.add_class::<PySignedBeaconBlockContentsMinimal>()?;
    m.add_class::<PyBlindedBeaconBlockMinimal>()?;
    m.add_class::<PySignedBlindedBeaconBlockMinimal>()?;

    // Gnosis classes
    m.add_class::<PySignedBeaconBlockGnosis>()?;
    m.add_class::<PyBeaconBlockContentsGnosis>()?;
    m.add_class::<PySignedBeaconBlockContentsGnosis>()?;
    m.add_class::<PyBlindedBeaconBlockGnosis>()?;
    m.add_class::<PySignedBlindedBeaconBlockGnosis>()?;

    Ok(())
}
