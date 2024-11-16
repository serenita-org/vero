import pytest

from spec.configs import Network, get_network_spec


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.CUSTOM],
)
def test_get_network_spec(network: Network) -> None:
    # TODO test currently failing because of missing Electra spec values
    _ = get_network_spec(network=network)
