# Compatibility

Vero regularly undergoes thorough testing against CL and EL client combinations using the Kurtosis [ethereum-package](https://github.com/ethpandaops/ethereum-package){:target="_blank"}.

It is currently compatible with all open-source Ethereum consensus layer clients:

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
