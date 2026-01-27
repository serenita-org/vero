import pytest

from spec.base import SpecGloas
from spec.configs import Network, get_network_spec


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.CUSTOM],
)
def test_get_network_spec(network: Network) -> None:
    spec, preset = get_network_spec(network=network)
    assert isinstance(spec, SpecGloas)
    assert preset in ("mainnet", "gnosis")
