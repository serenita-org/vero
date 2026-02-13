"""
Verify preset values match between YAML config files and Rust source code.

This script compares preset values for Gnosis (local), Mainnet, and Minimal (upstream).

Exits with a non-0 exit code if one or more mismatches are found.
"""

import re
from collections import namedtuple
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import yaml

# Mapping of typenum values to integers
TYPENUM_MAP = {}
for py_int in (
    1,
    2,
    4,
    8,
    16,
    17,
    32,
    64,
    128,
    256,
    512,
    1024,
    2048,
    4096,
    8192,
    65_536,
    262_144,
    1_048_576,
    134_217_728,
    16_777_216,
    1_073_741_824,
    1_099_511_627_776,
):
    TYPENUM_MAP[f"U{py_int}"] = py_int

GRANDINE_TAG = "2.0.1"
GRANDINE_PRESET_FILE_CONTENT = ""

# Preset configurations
PRESETS = {
    "gnosis": {
        "rust_file": "rust/grandine_bindings/src/preset_gnosis.rs",
        "yaml_dir": "src/spec/configs/presets/gnosis",
        "is_local": True,
    },
    "mainnet": {
        "rust_file": None,  # From upstream
        "yaml_dir": "src/spec/configs/presets/mainnet",
        "is_local": False,
    },
    "minimal": {
        "rust_file": None,  # From upstream
        "yaml_dir": "src/spec/configs/presets/minimal",
        "is_local": False,
    },
}


def camel_to_snake(name: str) -> str:
    """Convert CamelCase to UPPER_SNAKE_CASE.

    Examples:
        SlotsPerEpoch -> SLOTS_PER_EPOCH
        MaxAttestations -> MAX_ATTESTATIONS
        EpochsPerHistoricalVector -> EPOCHS_PER_HISTORICAL_VECTOR
        EpochsPerEth1VotingPeriod -> EPOCHS_PER_ETH1_VOTING_PERIOD
    """
    result = []
    for i, char in enumerate(name):
        if char.isupper():
            # Check if we need to insert an underscore before this uppercase letter
            if i > 0:
                prev_char = name[i - 1]
                next_char = name[i + 1] if i + 1 < len(name) else ""
                # Case 1: Previous char is lowercase (e.g., "slotsE" -> "SLOTS_E")
                # Case 2: Previous char is uppercase AND next char is lowercase
                #         (e.g., "ETHVoting" at 'V' -> "ETH_VOTING")
                # Case 3: Previous char is a digit AND next char is lowercase
                #         (e.g., "ETH1Voting" at 'V' -> "ETH1_VOTING")
                if prev_char.islower():
                    result.append("_")
                elif prev_char.isupper() and next_char and next_char.islower():
                    result.append("_")
                elif prev_char.isdigit() and next_char and next_char.islower():
                    result.append("_")
            result.append(char.upper())
        elif char.isdigit():
            # Digits: just append them (they're part of acronyms like ETH1)
            result.append(char)
        else:
            result.append(char.upper())
    return "".join(result)


def parse_yaml_value(raw_value: Any, key: str) -> int | None:
    """Parse a raw YAML value into an integer."""
    if raw_value is None:
        return None

    # If it's already an int, return it
    if isinstance(raw_value, int):
        return raw_value

    # If it's a string, try to parse it
    if isinstance(raw_value, str):
        value_str = raw_value.strip()
        # Remove inline comments
        value_str = value_str.split("#")[0].strip()

        # Try direct integer parsing (handle commas)
        try:
            return int(value_str.replace(",", ""))
        except ValueError:
            pass

        # Parse expressions like "2**6 (= 64)" or "2**0 * 10**9 (= 1,000,000,000)"
        expr_match = re.search(r"\(\=\s*([0-9,]+)\s*\)", value_str)
        if expr_match:
            return int(expr_match.group(1).replace(",", ""))

        # Parse raw power expressions
        power_match = re.search(r"(\d[\d,]*)", value_str)
        if power_match:
            return int(power_match.group(1).replace(",", ""))

    # If we get here, we couldn't parse the value - raise an error
    raise RuntimeError(f"Failed to parse YAML value for '{key}': {raw_value!r}")


def extract_rust_types(rust_content: str, preset_name: str) -> dict[str, str]:
    """Extract type definitions from Rust preset file."""
    types = {}

    if preset_name == "gnosis":
        # For Gnosis, extract from impl Preset for Gnosis
        pattern = r"type\s+(\w+)\s*=\s*(U\d+);"
        for match in re.finditer(pattern, rust_content):
            types[match.group(1)] = match.group(2)
    else:
        # For Mainnet/Minimal from upstream
        cap_name = preset_name.capitalize()
        impl_pattern = rf"impl\s+Preset\s+for\s+{cap_name}\s*\{{(.*?)\n\}}"
        impl_match = re.search(impl_pattern, rust_content, re.DOTALL)

        if impl_match:
            impl_content = impl_match.group(1)

            # First, handle delegate_preset_items! macro (Minimal delegates to Mainnet)
            if preset_name == "minimal":
                delegate_pattern = (
                    r"delegate_preset_items!\s*\{\s*super\s+Mainnet;([^}]+)\}"
                )
                delegate_match = re.search(delegate_pattern, impl_content, re.DOTALL)
                if delegate_match:
                    # Extract delegated type names (they end with semicolon)
                    for line in delegate_match.group(1).split("\n"):
                        line = line.strip()
                        if line.startswith("type ") and line.endswith(";"):
                            type_name = line[5:-1]  # Remove "type " and ";"
                            # These are delegated to Mainnet
                            types[type_name] = "DELEGATED_TO_MAINNET"

            # Extract explicit type definitions
            pattern = r"type\s+(\w+)\s*=\s*(U\d+);"
            for match in re.finditer(pattern, impl_content):
                types[match.group(1)] = match.group(2)

            # For Minimal, resolve delegated types from Mainnet
            if preset_name == "minimal":
                mainnet_types = {}
                mainnet_impl_pattern = r"impl\s+Preset\s+for\s+Mainnet\s*\{(.*?)\n\}"
                mainnet_match = re.search(mainnet_impl_pattern, rust_content, re.DOTALL)
                if mainnet_match:
                    mainnet_content = mainnet_match.group(1)
                    for match in re.finditer(pattern, mainnet_content):
                        mainnet_types[match.group(1)] = match.group(2)

                # Resolve delegated types
                for type_name, type_value in list(types.items()):
                    if (
                        type_value == "DELEGATED_TO_MAINNET"
                        and type_name in mainnet_types
                    ):
                        types[type_name] = mainnet_types[type_name]

    return types


def extract_trait_defaults(rust_content: str) -> dict[str, int]:
    """Extract default const values from the Preset trait definition."""
    consts = {}

    # Find the trait definition
    trait_pattern = r"pub trait Preset.*?\{(.*?)\n\}"
    trait_match = re.search(trait_pattern, rust_content, re.DOTALL)
    if not trait_match:
        return consts

    trait_content = trait_match.group(1)

    # Match pattern like "const BASE_REWARD_FACTOR: u64 = 64;" with default value
    pattern = r"const\s+(\w+)\s*:\s*(?:NonZeroU64|u64|Gwei|usize|u8)\s*=\s*(.+?);"
    for match in re.finditer(pattern, trait_content):
        name = match.group(1)
        value_str = match.group(2).strip()

        # Handle simple integer values
        try:
            consts[name] = int(value_str.replace("_", ""))
            continue
        except ValueError:
            pass

        # Handle nonzero!(value_u64) syntax - with or without underscores
        nz_match = re.search(r"nonzero!\((\d[\d_]*)_u64\)", value_str)
        if nz_match:
            consts[name] = int(nz_match.group(1).replace("_", ""))
            continue

        # Handle NonZeroU64::new(x).unwrap() or NonZeroU64::MIN
        nz_min_match = re.search(r"NonZeroU64::MIN", value_str)
        if nz_min_match:
            consts[name] = 1
            continue

        nz_new_match = re.search(r"NonZeroU64::new\((\d[\d_]*)\)", value_str)
        if nz_new_match:
            consts[name] = int(nz_new_match.group(1).replace("_", ""))
            continue

        # Handle bit shifts like "1_u64 << 26"
        shift_match = re.search(r"(\d+)_?u?\d*\s*<<\s*(\d+)", value_str)
        if shift_match:
            consts[name] = int(shift_match.group(1)) << int(shift_match.group(2))
            continue

        # If we get here, we couldn't parse the value - raise an error
        raise RuntimeError(
            f"Failed to parse Rust trait default for '{name}': {value_str!r}"
        )

    return consts


def extract_rust_consts(rust_content: str, preset_name: str) -> dict[str, int]:
    """Extract const definitions from Rust preset file."""
    consts = {}

    if preset_name == "gnosis":
        content_to_search = rust_content
        # Match pattern like "const BASE_REWARD_FACTOR: u64 = 25;"
        pattern = r"const\s+(\w+)\s*:\s*(?:NonZeroU64|u64|Gwei|usize|u8)\s*=\s*(.+?);"
        for match in re.finditer(pattern, content_to_search):
            name = match.group(1)
            value_str = match.group(2).strip()

            # Handle simple integer values
            try:
                consts[name] = int(value_str.replace("_", ""))
                continue
            except ValueError:
                pass

            # Handle NonZeroU64::new(x).unwrap() - with or without underscores
            nz_match = re.search(r"NonZeroU64::new\((\d[\d_]*)\)", value_str)

            if nz_match:
                consts[name] = int(nz_match.group(1).replace("_", ""))
                continue

            # Handle bit shifts like "1_u64 << 13"
            shift_match = re.search(r"(\d+)_?u?\d*\s*<<\s*(\d+)", value_str)
            if shift_match:
                consts[name] = int(shift_match.group(1)) << int(shift_match.group(2))
                continue

            # If we get here, we couldn't parse the value - raise an error
            raise RuntimeError(
                f"Failed to parse Rust const for '{name}' in Gnosis preset: {value_str!r}"
            )
    else:
        # For Mainnet/Minimal from upstream
        # First get default trait values
        trait_defaults = extract_trait_defaults(rust_content)

        # For Mainnet, it uses all trait defaults
        if preset_name == "mainnet":
            consts = trait_defaults.copy()

        # For Minimal, get the impl block overrides
        elif preset_name == "minimal":
            consts = trait_defaults.copy()  # Start with defaults

            # Find Minimal impl block
            impl_pattern = r"impl\s+Preset\s+for\s+Minimal\s*\{(.*?)\n\}"
            impl_match = re.search(impl_pattern, rust_content, re.DOTALL)
            if impl_match:
                impl_content = impl_match.group(1)

                # Match const overrides in Minimal impl
                pattern = (
                    r"const\s+(\w+)\s*:\s*(?:NonZeroU64|u64|Gwei|usize|u8)\s*=\s*(.+?);"
                )
                for match in re.finditer(pattern, impl_content):
                    name = match.group(1)
                    value_str = match.group(2).strip()

                    # Handle simple integer values
                    try:
                        consts[name] = int(value_str.replace("_", ""))
                        continue
                    except ValueError:
                        pass

                    # Handle nonzero!(value_u64) syntax
                    nz_match = re.search(r"nonzero!\((\d+)_u64\)", value_str)
                    if nz_match:
                        consts[name] = int(nz_match.group(1))
                        continue

                    # Handle bit shifts like "1_u64 << 25"
                    shift_match = re.search(r"(\d+)_?u?\d*\s*<<\s*(\d+)", value_str)
                    if shift_match:
                        consts[name] = int(shift_match.group(1)) << int(
                            shift_match.group(2)
                        )
                        continue

                    # If we get here, we couldn't parse the value - raise an error
                    raise RuntimeError(
                        f"Failed to parse Rust const for '{name}' in Minimal preset: {value_str!r}"
                    )

    return consts


def load_yaml_values(presets_dir: Path) -> dict[str, int]:
    """Load all relevant values from YAML preset files."""
    values = {}

    # Use all YAML files in the directory
    yaml_files = [f for f in presets_dir.iterdir() if f.suffix == ".yaml"]

    for filepath in yaml_files:
        with filepath.open() as f:
            parsed = yaml.load(f, yaml.BaseLoader)  # noqa: S506 - trusted input, BaseLoader is safe

        if not isinstance(parsed, dict):
            raise TypeError(f"Expected a dict from {filepath.name}, got {type(parsed)}")

        # Parse all keys from the YAML
        for key, raw_value in parsed.items():
            if key.startswith("#") or not isinstance(key, str):
                continue
            try:
                val = parse_yaml_value(raw_value, key)
            except RuntimeError:
                # Key exists but couldn't be parsed - this is expected for some keys
                # that have complex expressions. We'll skip them silently.
                continue
            if val is not None:
                values[key] = val

    return values


Mismatch = namedtuple(
    "Mismatch", ["rust_name", "yaml_value", "rust_value", "description"]
)


def verify_preset(preset_name: str, config: dict) -> tuple[int, list[Mismatch]]:
    """Verify a single preset. Returns (total, matched, mismatches)."""
    print(f"\n{'=' * 70}")
    print(f"Verifying {preset_name.capitalize()} Preset")
    print(f"{'=' * 70}")

    # Get worktree path (parent of scripts directory)
    script_dir = Path(__file__).parent.resolve()
    pwd = script_dir.parent

    presets_dir = pwd / config["yaml_dir"]

    # Load Rust content
    if config["is_local"]:
        rust_file = pwd / config["rust_file"]
        print(f"📖 Reading local Rust preset from: {rust_file}")
        with open(rust_file, "r") as f:
            rust_content = f.read()
    else:
        rust_content = GRANDINE_PRESET_FILE_CONTENT

    rust_types = extract_rust_types(rust_content, preset_name)
    rust_consts = extract_rust_consts(rust_content, preset_name)

    print(f"   Found {len(rust_types)} type definitions")
    print(f"   Found {len(rust_consts)} const definitions")

    # Load YAML values
    print(f"📖 Reading YAML presets from: {presets_dir}")
    yaml_values = load_yaml_values(presets_dir)
    print(f"   Found {len(yaml_values)} preset values")

    # Compare type-level values
    mismatches: list[Mismatch] = []
    type_params_checked = 0

    for rust_name, rust_typenum in rust_types.items():
        # Handle computed parameters
        if rust_name == "EpochsPerHistoricalRoot":
            yaml_val = (
                yaml_values["SLOTS_PER_HISTORICAL_ROOT"]
                // yaml_values["SLOTS_PER_EPOCH"]
            )
            source = "computed"
        elif rust_name == "CellsPerExtBlob":
            yaml_val = (
                yaml_values["FIELD_ELEMENTS_PER_EXT_BLOB"]
                // yaml_values["FIELD_ELEMENTS_PER_CELL"]
            )
            source = "computed"
        else:
            # Convert CamelCase Rust name to UPPER_SNAKE_CASE YAML key
            yaml_key = camel_to_snake(rust_name)
            yaml_val = yaml_values.get(yaml_key)
            source = yaml_key

        # Check for mismatches
        if yaml_val is None:
            mismatches.append(
                Mismatch(rust_name, None, rust_typenum, f"Missing in YAML ({source})")
            )
        elif rust_typenum not in TYPENUM_MAP:
            mismatches.append(
                Mismatch(
                    rust_name, None, rust_typenum, f"Unknown typenum {rust_typenum}"
                )
            )
        elif TYPENUM_MAP[rust_typenum] != yaml_val:
            mismatches.append(
                Mismatch(
                    rust_name,
                    yaml_val,
                    TYPENUM_MAP[rust_typenum],
                    f"Mismatch: YAML={yaml_val}, Rust={TYPENUM_MAP[rust_typenum]}",
                )
            )

        type_params_checked += 1

    # Compare const values
    const_params_checked = 0

    for rust_name, rust_val in rust_consts.items():
        # Const names are already UPPER_SNAKE_CASE, same as YAML keys
        yaml_key = rust_name
        yaml_val = yaml_values.get(yaml_key)

        const_params_checked += 1

        if yaml_val is None:
            mismatches.append(Mismatch(rust_name, None, rust_val, "missing in YAML"))
        elif rust_val != yaml_val:
            mismatches.append(Mismatch(rust_name, yaml_val, rust_val, None))

    # Check for YAML values that don't have corresponding Rust definitions
    # Build set of all Rust-defined keys (types converted to snake_case + consts)
    rust_type_keys = {camel_to_snake(name) for name in rust_types.keys()}
    rust_const_keys = set(rust_consts.keys())
    all_rust_keys = rust_type_keys | rust_const_keys

    # YAML keys that are not used in the Rust codebase
    yaml_inputs_unused_in_rust = {
        "SLOTS_PER_HISTORICAL_ROOT",  # Rust computes EpochsPerHistoricalRoot and uses that
    }

    # YAML keys that are computed from others in Rust
    computed_config_keys = {
        "UPDATE_TIMEOUT",  # Computed from SLOTS_PER_EPOCH * EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        "CELLS_PER_EXT_BLOB",  # Computed from FIELD_ELEMENTS_PER_EXT_BLOB // FIELD_ELEMENTS_PER_CELL
    }

    reverse_check_ok = True
    for yaml_key in sorted(yaml_values.keys()):
        if yaml_key in yaml_inputs_unused_in_rust or yaml_key in computed_config_keys:
            continue
        if yaml_key not in all_rust_keys:
            mismatches.append(
                Mismatch(yaml_key, yaml_values[yaml_key], None, "missing in Rust")
            )
            reverse_check_ok = False

    if reverse_check_ok:
        print("✅ All YAML values are defined in Rust")

    total = type_params_checked + const_params_checked

    return total, mismatches


def main() -> None:
    global GRANDINE_PRESET_FILE_CONTENT
    """Main entry point. Returns exit code."""
    print("=" * 70)
    print("Gnosis, Mainnet, and Minimal Preset Verification")
    print("=" * 70)

    # Download upstream Rust preset file content
    req = Request(
        f"https://raw.githubusercontent.com/grandinetech/grandine/refs/tags/{GRANDINE_TAG}/types/src/preset.rs"
    )
    with urlopen(req) as response:
        if response.status != 200:
            raise RuntimeError(
                f"Failed to retrieve Rust preset file content: {response.status}, {response.read()}"
            )
        GRANDINE_PRESET_FILE_CONTENT = response.read().decode("utf-8")

    all_preset_mismatches: list[tuple[str, Mismatch]] = []
    total_params = 0

    for preset_name, config in PRESETS.items():
        total, mismatches = verify_preset(preset_name, config)
        total_params += total
        all_preset_mismatches.extend([(preset_name, m) for m in mismatches])

    # Final summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)

    if all_preset_mismatches:
        print(
            f"❌ VERIFICATION FAILED: {len(all_preset_mismatches)} mismatch(es) found"
        )
        print(f"   Total checked: {total_params}")
        print(f"   Mismatched: {len(all_preset_mismatches)}")
        print("\nMismatches by preset:")
        for preset, mismatch in all_preset_mismatches:
            if mismatch.description:
                print(f"  - {preset}.{mismatch.rust_name}: {mismatch.description}")
            else:
                print(
                    f"  - {preset}.{mismatch.rust_name}: YAML={mismatch.yaml_value}, Rust={mismatch.rust_value}"
                )
        print("=" * 70)
        raise ValueError("Verification failed")
    else:
        print(f"✅ VERIFICATION PASSED: All {total_params} parameters match")


if __name__ == "__main__":
    main()
