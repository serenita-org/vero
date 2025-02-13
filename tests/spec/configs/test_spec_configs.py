import pytest

from spec.configs import Network, get_network_spec


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.CUSTOM],
)
def test_get_network_spec(network: Network) -> None:
    # TODO test currently failing because of missing Electra fork epochs
    if network in (Network.MAINNET, Network.GNOSIS):
        pytest.xfail("Electra fork epoch not set yet")
    _ = get_network_spec(network=network)
