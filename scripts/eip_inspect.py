"""Inspect live SolidServer API responses and validate parsed models.

Loads credentials from .env. Prints parsed model fields, any model_extra keys
(fields the API returns that our model doesn't declare yet), and class_parameters.
Also cross-checks list vs info key sets for each object type.

Usage:
    # Subnets — first 3
    poetry run python scripts/eip_inspect.py subnet

    # Subnets — filter by CIDR or name substring
    poetry run python scripts/eip_inspect.py subnet 10.84.20.0/24
    poetry run python scripts/eip_inspect.py subnet prod-dmz

    # Subnets — first 10
    poetry run python scripts/eip_inspect.py subnet --limit 10

    # Spaces — first 3
    poetry run python scripts/eip_inspect.py space

    # Spaces — filter by name substring
    poetry run python scripts/eip_inspect.py space prod
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
from eip_pydantic.models.base import SolidServerModel
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet



SEPARATOR = "─" * 72


def _print_section(title: str) -> None:
    print(f"\n{'━' * 72}")
    print(f"  {title}")
    print(f"{'━' * 72}")


def _print_model(m: SolidServerModel, *, label: str = "Parsed model") -> None:
    print(f"\n{label}:")
    declared = {k: v for k, v in m.model_dump().items() if v is not None}
    print(json.dumps(declared, indent=2, default=str))

    extras = m.model_extra or {}
    if extras:
        print("\n  ⚠  model_extra (fields NOT declared in our model):")
        print(json.dumps(extras, indent=2, default=str))
    else:
        print("\n  ✓  model_extra is empty — model covers all returned fields")

    cp = m.class_parameters
    if cp:
        print(f"\n  class_parameters (parsed): {cp}")
    cpp = m.class_parameters_properties
    if cpp:
        print(f"  class_parameters_properties: {cpp}")
    cpi = m.class_parameters_inheritance_source
    if cpi:
        print(f"  class_parameters_inheritance_source: {cpi}")
    tagged = m.tagged_class_parameters
    if tagged:
        print(f"  tagged_class_parameters: {tagged}")


def _model_extra_summary(models: list[SolidServerModel], model_name: str) -> None:
    _print_section(f"Summary: model_extra keys seen across all {model_name} results")
    all_extra: set[str] = set()
    for m in models:
        all_extra |= set(m.model_extra or {})
    if all_extra:
        print(f"  ⚠  Add these to models/{model_name.lower()}.py:  {sorted(all_extra)}")
    else:
        print(f"  ✓  No undeclared fields — {model_name} model is complete")


def _subnet_where(query: str) -> tuple[str, str]:
    """Return (description, WHERE-clause) for the given subnet query string."""
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


def _space_where(query: str) -> tuple[str, str]:
    """Return (description, WHERE-clause) for the given space query string."""
    return (
        f"name like '%{query}%'",
        f"site_name like '%{query}%'",
    )


def _cross_check(a: SolidServerModel, b: SolidServerModel) -> None:
    keys_a = set(a.model_dump(exclude_none=False)) | set(a.model_extra or {})
    keys_b = set(b.model_dump(exclude_none=False)) | set(b.model_extra or {})
    only_in_a = keys_a - keys_b
    only_in_b = keys_b - keys_a
    if only_in_a:
        print(f"  Keys only in list response:  {sorted(only_in_a)}")
    if only_in_b:
        print(f"  Keys only in info response:  {sorted(only_in_b)}")
    if not only_in_a and not only_in_b:
        print("  ✓  Both responses contain exactly the same set of keys")


def cmd_subnet(host: str, username: str, password: str, verify: bool | str, args: argparse.Namespace) -> None:
    subnets: list[Subnet] = []

    with Session(host, username, password, verify=verify) as s:
        if args.query:
            desc, where = _subnet_where(args.query)
            subnets = s.list(Subnet, where=where)
            _print_section(f"ip_block_subnet_list  WHERE {desc}")
            if not subnets:
                print("  (no results)")
                return
        else:
            subnets = s.list(Subnet, limit=args.limit)
            _print_section(f"ip_block_subnet_list  (limit={args.limit})")

    for i, sn in enumerate(subnets):
        print(f"\n{SEPARATOR}")
        _print_model(sn, label=f"Subnet [{i}]  id={sn.subnet_id}  {sn.start_hostaddr}–{sn.end_hostaddr}")  # noqa: RUF001

    if subnets:
        first_id = subnets[0].subnet_id
        _print_section(f"ip_block_subnet_info  subnet_id={first_id}")
        with Session(host, username, password, verify=verify) as s2:
            info = s2.get(Subnet, first_id)
        _print_model(info, label=f"Subnet info  id={info.subnet_id}")

        _print_section("Cross-check: keys in list[0] vs info")
        _cross_check(subnets[0], info)

    _model_extra_summary(list(subnets), "Subnet")


def cmd_space(host: str, username: str, password: str, verify: bool | str, args: argparse.Namespace) -> None:
    spaces: list[Space] = []

    with Session(host, username, password, verify=verify) as s:
        if args.query:
            desc, where = _space_where(args.query)
            spaces = s.list(Space, where=where)
            _print_section(f"ip_site_list  WHERE {desc}")
            if not spaces:
                print("  (no results)")
                return
        else:
            spaces = s.list(Space, limit=args.limit)
            _print_section(f"ip_site_list  (limit={args.limit})")

    for i, sp in enumerate(spaces):
        print(f"\n{SEPARATOR}")
        _print_model(sp, label=f"Space [{i}]  id={sp.site_id}  {sp.site_name!r}")

    if spaces:
        first_id = spaces[0].site_id
        _print_section(f"ip_site_info  site_id={first_id}")
        with Session(host, username, password, verify=verify) as s2:
            info = s2.get(Space, first_id)
        _print_model(info, label=f"Space info  id={info.site_id}  {info.site_name!r}")

        _print_section("Cross-check: keys in list[0] vs info")
        _cross_check(spaces[0], info)

    _model_extra_summary(list(spaces), "Space")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="TYPE")

    sub_subnet = subparsers.add_parser("subnet", help="Inspect IPv4 networks (blocks and subnets)")
    sub_subnet.add_argument(
        "query",
        nargs="?",
        help="CIDR (e.g. 10.84.20.0/24) or name substring. Omit for first --limit results.",
    )
    sub_subnet.add_argument("--limit", type=int, default=3, metavar="N",
                            help="Max results when no query given (default: 3).")

    sub_space = subparsers.add_parser("space", help="Inspect IPAM spaces (sites)")
    sub_space.add_argument(
        "query",
        nargs="?",
        help="Name substring to filter spaces. Omit for first --limit results.",
    )
    sub_space.add_argument("--limit", type=int, default=3, metavar="N",
                           help="Max results when no query given (default: 3).")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return

    host = os.environ["EIP_HOST"]
    username = os.environ["EIP_USERNAME"]
    password = os.environ["EIP_PASSWORD"]
    verify = os.environ.get("EIP_VERIFY", "true").lower() != "false"

    print(f"Connecting to https://{host}/ (verify={verify})")

    if args.command == "subnet":
        cmd_subnet(host, username, password, verify, args)
    elif args.command == "space":
        cmd_space(host, username, password, verify, args)


if __name__ == "__main__":
    main()
