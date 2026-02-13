from dataclasses import dataclass

from grandine_bindings import (
    ElectraBeaconBlockContentsGnosis,
    ElectraBeaconBlockContentsMainnet,
    ElectraBeaconBlockContentsMinimal,
    ElectraBlindedBeaconBlockGnosis,
    ElectraBlindedBeaconBlockMainnet,
    ElectraBlindedBeaconBlockMinimal,
)

from spec.configs import Preset

type ElectraBeaconBlockContentsType = (
    ElectraBeaconBlockContentsMainnet
    | ElectraBeaconBlockContentsGnosis
    | ElectraBeaconBlockContentsMinimal
)
type ElectraBlindedBeaconBlockType = (
    ElectraBlindedBeaconBlockMainnet
    | ElectraBlindedBeaconBlockGnosis
    | ElectraBlindedBeaconBlockMinimal
)


@dataclass(frozen=True)
class RustSSZTypes:
    ElectraBeaconBlockContents: type[ElectraBeaconBlockContentsType]
    ElectraBlindedBeaconBlock: type[ElectraBlindedBeaconBlockType]


_types: RustSSZTypes | None = None


def init_with_preset(preset: Preset) -> None:
    global _types

    if preset == "mainnet":
        _types = RustSSZTypes(
            ElectraBeaconBlockContents=ElectraBeaconBlockContentsMainnet,
            ElectraBlindedBeaconBlock=ElectraBlindedBeaconBlockMainnet,
        )
    elif preset == "minimal":
        _types = RustSSZTypes(
            ElectraBeaconBlockContents=ElectraBeaconBlockContentsMinimal,
            ElectraBlindedBeaconBlock=ElectraBlindedBeaconBlockMinimal,
        )
    elif preset == "gnosis":
        _types = RustSSZTypes(
            ElectraBeaconBlockContents=ElectraBeaconBlockContentsGnosis,
            ElectraBlindedBeaconBlock=ElectraBlindedBeaconBlockGnosis,
        )
    else:
        raise NotImplementedError(f"Unknown preset {preset}")


def rust_ssz_types() -> RustSSZTypes:
    if _types is None:
        raise RuntimeError("init_with_preset was not called!")
    return _types
