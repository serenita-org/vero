# Compatibility

Vero is regularly tested against CL and EL client pairs using the Kurtosis [ethereum-package](https://github.com/ethpandaops/ethereum-package){:target="_blank"}.

Vero is currently compatible with all open-source Ethereum consensus layer (CL) clients:

|                | Compatible | Version  | Notes |
|----------------|------------|----------|-------|
| **Caplin**     | ✅          | v3.0.0+  |       |
| **Grandine**   | ✅          | 1.1.0+   |       |
| **Lighthouse** | ✅          | v7.0.0+  |       |
| **Lodestar**   | ✅          | v1.29.0+ |       |
| **Nimbus**     | ✅          | v25.4.0+ |       |
| **Prysm**      | ✅          | v6.0.0+  |       |
| **Teku**       | ✅          | 25.4.1+  |       |

!!! info "Legend"

    ✅ No known issues.

    🟡 Minor issues that do not prevent validator duties from working, but they may not work ideally.

    🟠 Issues that may impact some validator duties occasionally.

    🔴 Major issues that prevent validator duties from being performed.

!!! note "Compatibility Updates"

    This compatibility table is updated with each Vero release.
    If you encounter issues with a client version not listed here,
    please [open an issue on GitHub](https://github.com/serenita-org/vero/issues){:target="_blank"}.
