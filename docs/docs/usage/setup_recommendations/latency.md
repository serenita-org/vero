# A note on latency

Latency between Vero and its connected beacon nodes can affect validator
performance, though measures are in place that tolerate moderate network
delays.

Vero does not need to wait for responses from *all* connected beacon nodes.
If the fastest responses form a majority and agree, Vero proceeds without
waiting for the slower ones. This design keeps performance stable even
if some nodes are slower or become unresponsive.

## Recommendation

While lower latency is always better, based on our experience, Vero operates
reliably as long as the **round-trip time (RTT)** between Vero and each
connected beacon node remains roughly under **200 ms**. This number may
be lower for networks with shorter slot times, like Gnosis Chain.

We've tested setups spanning a single continent without issue, but
cross-continent configurations have not been tested.
