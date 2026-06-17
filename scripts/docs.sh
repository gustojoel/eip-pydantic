#!/usr/bin/env bash
# Build or serve HTML documentation via pdoc.
#
# Usage:
#   scripts/docs.sh          — build into site/
#   scripts/docs.sh --serve  — live-preview in the browser
#
# Submodules are listed explicitly so that their module docstrings
# (including the expressions guide via .. include::) appear as separate
# pages rather than being flattened into the top-level package page.

set -euo pipefail

MODULES=(
    eip_pydantic
    eip_pydantic.class_params
    eip_pydantic.client
    eip_pydantic.exceptions
    eip_pydantic.expressions
    eip_pydantic.models
    eip_pydantic.models.address
    eip_pydantic.models.base
    eip_pydantic.models.pool
    eip_pydantic.models.space
    eip_pydantic.models.subnet
    eip_pydantic.models.vrf
    eip_pydantic.session
)

if [[ "${1:-}" == "--serve" ]]; then
    exec poetry run pdoc -d google "${MODULES[@]}"
else
    exec poetry run pdoc -d google -o site/ "${MODULES[@]}"
fi
