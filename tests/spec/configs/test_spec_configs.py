import pytest

from spec.configs import Network, get_network_spec


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.CUSTOM],
)
def test_get_network_spec(network: Network) -> None:
    if network in (
        Network.GNOSIS,
        Network.CHIADO,
    ):
        pytest.skip(f"Fulu config values not available for {network} yet")

    _ = get_network_spec(network=network)
