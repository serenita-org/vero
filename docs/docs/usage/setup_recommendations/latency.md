# A note on latency

Vero has been successfully tested with
beacon nodes spanning a single continent, but not
across multiple continents.

Vero does not need to wait for responses from all
connected beacon nodes. If the fastest responses
form a majority and agree, Vero proceeds without
waiting for the slower ones.
These measures ensure that
a single slow or unresponsive beacon node does not
negatively affect validator performance.
