"""Inspect live ip_block_subnet_list / ip_block_subnet_info responses.

Loads credentials from .env, fetches subnets, and prints:
  - the raw JSON dict from the API
  - the parsed Subnet model fields
  - any model_extra keys (fields the API returns that aren't in our model)
  - the class_parameters property output

Usage:
    # Show the first 3 subnets
    poetry run python scripts/inspect_subnets.py

    # Filter by CIDR  (looks up the exact block/subnet for that prefix)
    poetry run python scripts/inspect_subnets.py 10.84.20.0/24

    # Filter by name substring  (SQL LIKE match)
    poetry run python scripts/inspect_subnets.py prod-dmz
"""

import argparse
import ipaddress
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from eip_pydantic import Session
from eip_pydantic.models.subnet import Subnet

SEPARATOR = "─" * 72


def _print_section(title: str) -> None:
    print(f"\n{'━' * 72}")
    print(f"  {title}")
    print(f"{'━' * 72}")


def _print_raw(label: str, data: object) -> None:
    print(f"\n{label}:")
    print(json.dumps(data, indent=2, default=str))


def _print_subnet(s: Subnet, *, label: str = "Parsed Subnet") -> None:
    print(f"\n{label}:")
    declared = {k: v for k, v in s.model_dump().items() if v is not None}
    print(json.dumps(declared, indent=2, default=str))

    extras = s.model_extra or {}
    if extras:
        print(f"\n  ⚠  model_extra (fields NOT declared in our Subnet model):")
        print(json.dumps(extras, indent=2, default=str))
    else:
        print("\n  ✓  model_extra is empty — model covers all returned fields")

    cp = s.class_parameters
    if cp:
        print(f"\n  class_parameters (parsed): {cp}")
    cpp = s.class_parameters_properties
    if cpp:
        print(f"  class_parameters_properties: {cpp}")
    cpi = s.class_parameters_inheritance_source
    if cpi:
        print(f"  class_parameters_inheritance_source: {cpi}")
    tagged = s.tagged_class_parameters
    if tagged:
        print(f"  tagged_class_parameters: {tagged}")


def _build_where(query: str) -> tuple[str, str]:
    """Return (description, WHERE-clause) for the given query string."""
    if "/" in query:
        net = ipaddress.ip_network(query, strict=False)
        addr = str(net.network_address)
        size = net.num_addresses
        return (
            f"CIDR {net}",
            f"start_hostaddr='{addr}' and subnet_size='{size}'",
        )
    return (
        f"name like '%{query}%'",
        f"subnet_name like '%{query}%'",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "query",
        nargs="?",
        help="CIDR (e.g. 10.84.20.0/24) or name substring to filter subnets. "
             "Omit to show the first 3 subnets.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Max results when no query given (default: 3).",
    )
    args = parser.parse_args()

    host = os.environ["EIP_HOST"]
    username = os.environ["EIP_USERNAME"]
    password = os.environ["EIP_PASSWORD"]
    verify = os.environ.get("EIP_VERIFY", "true").lower() != "false"

    print(f"Connecting to https://{host}/ (verify={verify})")

    with Session(host, username, password, verify=verify) as s:

        if args.query:
            desc, where = _build_where(args.query)

            # ---- Raw JSON ------------------------------------------------
            _print_section(f"ip_block_subnet_list  WHERE {desc}  — raw JSON")
            raw_list: object = s._client.get("rest/ip_block_subnet_list", WHERE=where)
            _print_raw("raw response", raw_list)

            # ---- Parsed subnets -----------------------------------------
            subnets = s.list(Subnet, where=where)
            _print_section(f"ip_block_subnet_list  WHERE {desc}  — parsed as Subnet")
            if not subnets:
                print("  (no results)")
                return
            for i, sn in enumerate(subnets):
                print(f"\n{SEPARATOR}")
                _print_subnet(sn, label=f"Subnet [{i}]  id={sn.subnet_id}  {sn.start_hostaddr}–{sn.end_hostaddr}")

        else:
            # ---- Default: first N subnets --------------------------------
            _print_section(f"ip_block_subnet_list  (limit={args.limit})  — raw JSON")
            raw_list = s._client.get("rest/ip_block_subnet_list", limit=args.limit)
            _print_raw("raw response", raw_list)

            subnets = s.list(Subnet, limit=args.limit)
            _print_section(f"ip_block_subnet_list  — parsed as Subnet")
            for i, sn in enumerate(subnets):
                print(f"\n{SEPARATOR}")
                _print_subnet(sn, label=f"Subnet [{i}]  id={sn.subnet_id}  {sn.start_hostaddr}–{sn.end_hostaddr}")

        # ---- ip_block_subnet_info on the first result -------------------
        if subnets:
            first_id = subnets[0].subnet_id
            _print_section(f"ip_block_subnet_info  subnet_id={first_id}  — raw JSON")
            raw_info: object = s._client.get("rest/ip_block_subnet_info", subnet_id=first_id)
            _print_raw("raw response", raw_info)

            _print_section(f"ip_block_subnet_info  subnet_id={first_id}  — parsed as Subnet")
            info = Subnet.parse_response("info", raw_info)
            _print_subnet(info, label=f"Subnet info  id={info.subnet_id}")

            # ---- Cross-check keys ----------------------------------------
            _print_section("Cross-check: keys in list[0] vs info")
            list_keys = set(subnets[0].model_dump(exclude_none=False)) | set(subnets[0].model_extra or {})
            info_keys = set(info.model_dump(exclude_none=False)) | set(info.model_extra or {})
            only_in_list = list_keys - info_keys
            only_in_info = info_keys - list_keys
            if only_in_list:
                print(f"  Keys only in list response:  {sorted(only_in_list)}")
            if only_in_info:
                print(f"  Keys only in info response:  {sorted(only_in_info)}")
            if not only_in_list and not only_in_info:
                print("  ✓  Both responses contain exactly the same set of keys")

        # ---- Summary of undeclared fields --------------------------------
        _print_section("Summary: model_extra keys seen across all results")
        all_extra: set[str] = set()
        for sn in subnets:
            all_extra |= set(sn.model_extra or {})
        if all_extra:
            print(f"  ⚠  Add these to models/subnet.py Subnet:  {sorted(all_extra)}")
        else:
            print("  ✓  No undeclared fields — Subnet model is complete")


if __name__ == "__main__":
    main()
