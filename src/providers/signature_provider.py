from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from schemas import SchemaRemoteSigner


class SignatureProvider:
    async def sign(
        self,
        message: SchemaRemoteSigner.SignableMessageT,
        identifier: str,
    ) -> tuple[SchemaRemoteSigner.SignableMessageT, str, str]:
        raise NotImplementedError

    async def sign_in_batches(
        self,
        messages: list[SchemaRemoteSigner.SignableMessageT],
        identifiers: list[str],
        batch_size: int = 100,
    ) -> list[tuple[SchemaRemoteSigner.SignableMessageT, str, str]]:
        raise NotImplementedError

    async def get_public_keys(self) -> list[str]:
        raise NotImplementedError
