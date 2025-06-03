def encode_graffiti(graffiti_string: str) -> bytes:
    _graffiti_max_bytes = 32

    encoded = graffiti_string.encode("utf-8").ljust(_graffiti_max_bytes, b"\x00")
    if len(encoded) > _graffiti_max_bytes:
        raise ValueError(
            f"Encoded graffiti exceeds the maximum length of {_graffiti_max_bytes} bytes"
        )

    return encoded


def decode_graffiti(graffiti_bytes: bytes) -> str:
    return graffiti_bytes.rstrip(b"\x00").decode("utf-8")
