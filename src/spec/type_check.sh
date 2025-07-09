#!/bin/bash
violations=$(grep -r --include="*.py" ": uint" ./src/spec)

if [[ -n "$violations" ]]; then
  echo "ERROR: Found use of 'uint' type. Use the 'SerializedAsString' variant instead."
  echo "$violations"
  exit 1
fi
