from functools import lru_cache

from remerkleable.byte_arrays import Bytes4, Bytes32
from remerkleable.complex import Container

from spec.base import Version
from spec.common import Epoch, Root


class DomainType(Bytes4):
    pass


DOMAIN_BEACON_PROPOSER = DomainType("0x00000000")
DOMAIN_BEACON_ATTESTER = DomainType("0x01000000")
DOMAIN_RANDAO = DomainType("02000000")
DOMAIN_DEPOSIT = DomainType("03000000")
DOMAIN_VOLUNTARY_EXIT = DomainType("04000000")
DOMAIN_SELECTION_PROOF = DomainType("05000000")
DOMAIN_AGGREGATE_AND_PROOF = DomainType("06000000")
DOMAIN_SYNC_COMMITTEE = DomainType("07000000")
DOMAIN_SYNC_COMMITTEE_SELECTION_PROOF = DomainType("08000000")
DOMAIN_CONTRIBUTION_AND_PROOF = DomainType("09000000")
DOMAIN_APPLICATION_MASK = DomainType("0a000000")


class Domain(Bytes32):
    pass


class SigningData(Container):
    object_root: Root
    domain: Domain


class ForkData(Container):
    current_version: Version
    genesis_validators_root: Root


class RandaoReveal(Container):
    epoch: Epoch


def compute_fork_data_root(
    current_version: Version, genesis_validators_root: Root
) -> Root:
    """
    Return the 32-byte fork data root for the ``current_version`` and ``genesis_validators_root``.
    This is used primarily in signature domains to avoid collisions across forks/chains.
    """
    return ForkData(  # type: ignore[no-any-return]
        current_version=current_version, genesis_validators_root=genesis_validators_root
    ).hash_tree_root()


def compute_domain(
    domain_type: DomainType, fork_version: Version, genesis_validators_root: Root
) -> Domain:
    """
    Return the domain for the ``domain_type`` and ``fork_version``.
    """
    fork_data_root = compute_fork_data_root(fork_version, genesis_validators_root)
    return Domain(domain_type + fork_data_root[:28])


@lru_cache(maxsize=1)
def compute_domain_attester(
    fork_version: Version, genesis_validators_root: Root
) -> Domain:
    return compute_domain(
        domain_type=DOMAIN_BEACON_ATTESTER,
        fork_version=fork_version,
        genesis_validators_root=genesis_validators_root,
    )


@lru_cache(maxsize=1)
def compute_domain_proposer(
    fork_version: Version, genesis_validators_root: Root
) -> Domain:
    return compute_domain(
        domain_type=DOMAIN_BEACON_PROPOSER,
        fork_version=fork_version,
        genesis_validators_root=genesis_validators_root,
    )


def compute_signing_root(ssz_object: Container, domain: Domain) -> Root:
    """
    Return the signing root for the corresponding signing data.
    """
    return SigningData(  # type: ignore[no-any-return]
        object_root=ssz_object.hash_tree_root(), domain=domain
    ).hash_tree_root()
