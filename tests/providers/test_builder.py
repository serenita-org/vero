import pytest
from yarl import URL

from providers.builder import get_default_auth_data



@pytest.mark.parametrize(
    argnames=("builder_url", "expected_auth_data"),
    argvalues=[
        pytest.param(
            URL("https://builder.example.com/"),
            b"builder.example.com",
        ),
        pytest.param(
            URL("HTTPS://Builder.Example.com:443/bids?x=1"),
            b"builder.example.com",
        ),
        pytest.param(
            URL("https://builder.example.com:8080"),
            b"builder.example.com",
        ),
        pytest.param(
            URL("https://user:pw@builder.example.com/"),
            b"builder.example.com",
        ),
        pytest.param(
            URL("https://10.0.0.5:18550/eth/v1/builder"),
            b"10.0.0.5",
        ),
        pytest.param(
            URL("https://[0:0:0:0:0:0:0:1]:8443/"),
            b"[::1]",
        ),
        pytest.param(
            URL("https://[::ffff:192.0.2.1]/"),
            b"[::ffff:c000:201]",
        )
    ]
)
async def test_get_default_auth_data(builder_url: URL, expected_auth_data: bytes) -> None:
    assert get_default_auth_data(builder_url) == expected_auth_data
