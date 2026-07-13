from collections.abc import Iterable

BITS_PER_BYTE = 8


class _Bitfield(list[bool]):
    limit: int
    bitlist: bool

    def __init__(self, values: Iterable[bool | int] = ()) -> None:
        super().__init__(bool(value) for value in values)

    @classmethod
    def __class_getitem__(cls, limit: int) -> type["_Bitfield"]:  # type: ignore[override]
        return type(f"{cls.__name__}{limit}", (cls,), {"limit": limit})

    def to_obj(self) -> str:
        length = len(self) if self.bitlist else self.limit
        output = bytearray(
            (length + int(self.bitlist) + BITS_PER_BYTE - 1) // BITS_PER_BYTE
        )
        for index, value in enumerate(self):
            if value:
                output[index // BITS_PER_BYTE] |= 1 << (index % BITS_PER_BYTE)
        if self.bitlist:
            output[len(self) // BITS_PER_BYTE] |= 1 << (len(self) % BITS_PER_BYTE)
        return f"0x{output.hex()}"


class Bitlist(_Bitfield):
    bitlist = True


class Bitvector(_Bitfield):
    bitlist = False
