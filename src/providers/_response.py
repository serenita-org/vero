import aiohttp


def raise_for_response_size(
    response: aiohttp.ClientResponse,
    max_bytes: int,
) -> None:
    if response.content_length is not None and response.content_length > max_bytes:
        raise ValueError(
            f"Response body too large for {response.request_info.url}: "
            f"{response.content_length} bytes exceeds limit of {max_bytes} bytes",
        )
