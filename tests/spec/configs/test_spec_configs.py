import pytest

from spec.base import SpecGloas
from spec.configs import Network, get_network_spec


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.CUSTOM],
)
def test_get_network_spec(network: Network) -> None:
    if network in (Network.MAINNET, Network.GNOSIS, Network.CHIADO):
        pytest.skip("Gloas configs not yet available yet for these networks")
    spec, preset = get_network_spec(network=network)
    assert isinstance(spec, SpecGloas)
    # There are only two presets Vero supports
    assert preset in ("mainnet", "gnosis")
