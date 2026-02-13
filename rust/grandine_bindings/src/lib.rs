//! SSZ encoding/decoding library using Grandine for Ethereum consensus types.
//!
//! This crate provides Python bindings for SSZ serialization/deserialization
//! of Ethereum consensus layer types (Beacon blocks, etc.) using the Grandine
//! consensus client library.
//!
//! Supported presets:
//! - Mainnet
//! - Minimal
//! - Gnosis
//!
//! # Example
//!
//! ```python
//! from grandine_bindings import SignedBeaconBlockMainnet
//!
//! # Decode from SSZ bytes
//! block = SignedBeaconBlockMainnet.from_ssz(ssz_bytes)
//!
//! # Encode to SSZ bytes
//! ssz_bytes = block.to_ssz()
//! ```

use pyo3::prelude::*;

mod electra;
mod macros;
mod preset_gnosis;

pub use macros::{decode_ssz, encode_ssz};
pub use preset_gnosis::Gnosis;

#[pymodule]
fn grandine_bindings(m: &Bound<'_, PyModule>) -> PyResult<()> {
    electra::block::register(m)?;
    Ok(())
}
