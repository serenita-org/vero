from spec.common import Uint64
from spec.constants import BASIS_POINTS


def get_slot_component_duration_ms(
    basis_points: Uint64, slot_duration_ms: Uint64
) -> int:
    """
    Calculate the duration of a slot component in milliseconds.
    """
    return int(basis_points * slot_duration_ms // BASIS_POINTS)
