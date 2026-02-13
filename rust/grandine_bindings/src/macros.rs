//! Macro for defining SSZ-enabled Python classes.
//!
//! This module provides the `define_ssz_pyclass_for_preset!` macro which generates
//! Python class definitions for SSZ-serializable types with support for different
//! Ethereum presets (Mainnet, Minimal, Gnosis).

use grandine_ssz::{SszRead, SszReadDefault as _, SszWrite};

/// Decodes SSZ-encoded bytes into a type.
///
/// # Errors
///
/// Returns an error string if the bytes cannot be decoded as the target type.
pub fn decode_ssz<T: SszRead<()>>(bytes: &[u8]) -> Result<T, String> {
    T::from_ssz_default(bytes).map_err(|e| e.to_string())
}

/// Encodes a value to SSZ bytes.
///
/// # Errors
///
/// Returns an error string if the value cannot be encoded.
pub fn encode_ssz<T: SszWrite>(value: &T) -> Result<Vec<u8>, String> {
    value.to_ssz().map_err(|e| e.to_string())
}

/// Defines a Python class for an SSZ-serializable type with preset support.
///
/// This macro generates a pyo3 class with standard SSZ and JSON serialization
/// methods, plus optional extra methods.
///
/// # Arguments
///
/// * `$rust_struct` - The name for the generated Rust struct
/// * `$py_name` - The Python class name (as a string literal)
/// * `$rust_ty` - The underlying Rust type being wrapped
/// * `extra_methods` (optional) - Additional methods to add to the class
///
/// # Generated Methods
///
/// * `from_ssz` - Deserialize from SSZ bytes
/// * `to_ssz` - Serialize to SSZ bytes
/// * `from_json` - Deserialize from JSON bytes (requires `DeserializeOwned`)
/// * `to_json` - Serialize to JSON bytes (requires `Serialize`)
///
/// # Example
///
/// ```ignore
/// define_ssz_pyclass_for_preset!(
///     PySignedBeaconBlockMainnet,
///     "SignedBeaconBlockMainnet",
///     SignedBeaconBlock<Mainnet>
/// );
/// ```
#[macro_export]
macro_rules! define_ssz_pyclass_for_preset {
    (
        $rust_struct:ident,
        $py_name:literal,
        $rust_ty:ty
        $(, extra_methods = { $($extra:tt)* } )?
    ) => {
        #[pyo3::prelude::pyclass(name = $py_name)]
        pub struct $rust_struct {
            pub(crate) inner: $rust_ty,
        }

        #[pyo3::prelude::pymethods]
        impl $rust_struct {
            #[staticmethod]
            /// Deserialize from SSZ-encoded bytes.
            ///
            /// # Errors
            /// Returns `PyValueError` if deserialization fails.
            pub fn from_ssz(
                b: &pyo3::Bound<'_, pyo3::types::PyBytes>,
            ) -> pyo3::PyResult<Self> {
                let inner: $rust_ty = $crate::decode_ssz(b.as_bytes())
                    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
                Ok(Self { inner })
            }

            #[staticmethod]
            /// Deserialize from JSON-encoded bytes.
            ///
            /// Expects JSON in the format `{"data": <value>}`.
            ///
            /// # Errors
            /// Returns `PyValueError` if deserialization fails.
            pub fn from_json(
                b: &pyo3::Bound<'_, pyo3::types::PyBytes>,
            ) -> pyo3::PyResult<Self>
            where
                $rust_ty: serde::de::DeserializeOwned,
            {
                #[derive(serde::Deserialize)]
                struct Envelope<T> {
                    data: T,
                }

                let env: Envelope<$rust_ty> = serde_json::from_slice(b.as_bytes())
                    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

                Ok(Self { inner: env.data })
            }

            /// Serialize to SSZ-encoded bytes.
            ///
            /// # Errors
            /// Returns `PyValueError` if serialization fails.
            pub fn to_ssz(
                &self,
                py: pyo3::Python<'_>,
            ) -> pyo3::PyResult<pyo3::Py<pyo3::types::PyBytes>> {
                let out = $crate::encode_ssz(&self.inner)
                    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))?;
                Ok(pyo3::types::PyBytes::new(py, &out).into())
            }

            /// Serialize to JSON-encoded bytes.
            ///
            /// # Errors
            /// Returns `PyValueError` if serialization fails.
            pub fn to_json(
                &self,
                py: pyo3::Python<'_>,
            ) -> pyo3::PyResult<pyo3::Py<pyo3::types::PyBytes>>
            where
                $rust_ty: serde::Serialize,
            {
                let out = serde_json::to_vec(&self.inner)
                    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
                Ok(pyo3::types::PyBytes::new(py, &out).into())
            }

            $($($extra)*)?
        }
    };
}
