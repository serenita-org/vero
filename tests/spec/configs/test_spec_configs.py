import pytest

from spec.configs import Network, get_network_spec


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.FETCH],
)
def test_get_network_spec(network: Network) -> None:
    _ = get_network_spec(network=network)
