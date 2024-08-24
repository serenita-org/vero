# Compatibility

Vero regularly undergoes thorough testing against various CL and EL client combinations using [Kurtosis](https://github.com/kurtosis-tech/kurtosis) and the amazing [ethereum-package](https://github.com/ethpandaops/ethereum-package).

It is currently compatible with all open-source Ethereum clients:

|                | Compatible | Version  | Notes                                                                |
|----------------|------------|----------|----------------------------------------------------------------------|
| **Grandine**   | 🟡         | 0.4.0+   | Slashing SSE events not supported yet - slashing detection is slower |
| **Lighthouse** | ✅          | v4.6.0+  |                                                                      |
| **Lodestar**   | ✅          | v1.12.0+ |                                                                      |
| **Nimbus**     | ✅          | v24.1.1+ |                                                                      |
| **Prysm**      | ✅          | v4.2.0   |                                                                      |
| **Teku**       | ✅          | 23.11.0+ |                                                                      |

#### Legend
✅ Everything works perfectly.

🟡 Minor issues that do not prevent validator duties from working but they may not work ideally.

🟠 Issues that may impact some validator duties occasionally.

🔴 Major issues that prevent validator duties from being performed.
