# Compatibility

Vero regularly undergoes thorough testing against various CL and EL client combinations using [Kurtosis](https://github.com/kurtosis-tech/kurtosis) and the amazing [ethereum-package](https://github.com/ethpandaops/ethereum-package).

It is currently compatible with all open-source Ethereum clients:

|                | Compatible | Version        | Notes |
|----------------|------------|----------------|-------|
| **Grandine**   | ✅          | 1.0.0+         |       |
| **Lighthouse** | ✅          | v7.0.0-beta.0+ |       |
| **Lodestar**   | ✅          | v1.27.0-rc.1+  |       |
| **Nimbus**     | ✅          | v25.2.0+       |       |
| **Prysm**      | ✅          | v5.3.0+        |       |
| **Teku**       | ✅          | 25.2.0+        |       |

#### Legend
✅ Everything works perfectly.

🟡 Minor issues that do not prevent validator duties from working but they may not work ideally.

🟠 Issues that may impact some validator duties occasionally.

🔴 Major issues that prevent validator duties from being performed.
