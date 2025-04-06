import pytest
import remerkleable.core

from spec.configs import Network, get_network_spec


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.CUSTOM],
)
def test_get_network_spec(network: Network) -> None:
    if network in (Network.MAINNET,):
        # Electra fork epoch not defined in config
        with pytest.raises(remerkleable.core.ObjParseException):
            get_network_spec(network)
    else:
        _ = get_network_spec(network=network)
