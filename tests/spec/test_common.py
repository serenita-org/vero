import pytest

from spec.common import Uint64


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(0, 0),
        pytest.param("18446744073709551615", 2**64 - 1),
    ],
)
def test_uint64(value: int | str, expected: int) -> None:
    uint64 = Uint64(value)

    assert uint64 == expected
    assert uint64.to_obj() == str(expected)


@pytest.mark.parametrize("value", [-1, 2**64])
def test_uint64_rejects_out_of_range_value(value: int) -> None:
    with pytest.raises(ValueError, match="uint64 value out of range"):
        Uint64(value)


def test_uint64_deserialization_requires_string() -> None:
    assert Uint64.from_obj("42") == 42

    with pytest.raises(
        TypeError,
        match="uint64 JSON value must be a string, got int",
    ):
        Uint64.from_obj(42)  # type: ignore[arg-type]
