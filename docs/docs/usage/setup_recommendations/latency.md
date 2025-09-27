# A note on latency

Vero has been successfully tested with
beacon nodes spanning a single continent. It has
not been tested with beacon nodes spanning several
continents.

Vero does not always need to collect responses
from all the connected beacon nodes. If the
fastest responses form a majority of connected
beacon nodes agree, it will not wait for the rest
of the responses to come in and will move on.
These kinds of measures are in place to make sure
a single slow or unresponsive beacon node doesn't
have a negative effect on validator performance.
