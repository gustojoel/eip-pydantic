"""Inspect live SolidServer API responses and validate parsed models.

Loads credentials from .env. Prints parsed model fields, any model_extra keys
(fields the API returns that our model doesn't declare yet), and class_parameters.
Also cross-checks list vs info key sets for each object type, and reports count.

Usage:
    # Subnets — first 3
    poetry run python scripts/eip_inspect.py subnet

    # Subnets — filter by CIDR or name substring
    poetry run python scripts/eip_inspect.py subnet 10.84.20.0/24
    poetry run python scripts/eip_inspect.py subnet prod-dmz

    # Spaces — first 3
    poetry run python scripts/eip_inspect.py space

    # Spaces — filter by name substring
    poetry run python scripts/eip_inspect.py space prod

    # Pools — first 3 (optionally filter by pool or subnet name substring)
    poetry run python scripts/eip_inspect.py pool
    poetry run python scripts/eip_inspect.py pool dhcp-range

    # IPv4 addresses — first 3 (optionally filter by address or name substring)
    poetry run python scripts/eip_inspect.py address
    poetry run python scripts/eip_inspect.py address 10.84.20.5
    poetry run python scripts/eip_inspect.py address gateway
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
from eip_pydantic.class_params import ClassParamDict
from eip_pydantic.models.address import IpAddress
from eip_pydantic.models.base import SolidServerModel
from eip_pydantic.models.pool import Pool
from eip_pydantic.models.space import Space
from eip_pydantic.models.subnet import Subnet



SEPARATOR = "─" * 72


def _print_section(title: str) -> None:
    print(f"\n{'━' * 72}")
    print(f"  {title}")
    print(f"{'━' * 72}")


def _print_model(m: SolidServerModel, *, label: str = "Parsed model") -> None:
    print(f"\n{label}:")
    declared = {
        k: v for k, v in m.model_dump().items()
        if v is not None and not isinstance(v, ClassParamDict)
    }
    print(json.dumps(declared, indent=2, default=str))

    extras = m.model_extra or {}
    if extras:
        print("\n  ⚠  model_extra (fields NOT declared in our model):")
        print(json.dumps(extras, indent=2, default=str))
    else:
        print("\n  ✓  model_extra is empty — model covers all returned fields")

    for field_name in type(m).model_fields:
        cp = getattr(m, field_name, None)
        if isinstance(cp, ClassParamDict) and cp:
            print(f"\n  {field_name}: {dict(cp.items())}")

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


def _print_count(host: str, username: str, password: str, verify: bool | str,
                 cls: type[SolidServerModel], where: str | None = None) -> None:
    with Session(host, username, password, verify=verify) as s:
        n = s.count(cls, where=where)
    label = f"WHERE {where}" if where else "(no filter)"
    print(f"\n  count {label}: {n}")


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

    _print_section("ip_block_subnet_count")
    _print_count(host, username, password, verify, Subnet)

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

    _print_section("ip_site_count")
    _print_count(host, username, password, verify, Space)

    _model_extra_summary(list(spaces), "Space")


def cmd_pool(host: str, username: str, password: str, verify: bool | str, args: argparse.Namespace) -> None:
    pools: list[Pool] = []
    where: str | None = None

    with Session(host, username, password, verify=verify) as s:
        if args.query:
            where = f"pool_name like '%{args.query}%'"
            pools = s.list(Pool, where=where)
            _print_section(f"ip_pool_list  WHERE pool_name like '%{args.query}%'")
            if not pools:
                print("  (no results)")
                return
        else:
            pools = s.list(Pool, limit=args.limit)
            _print_section(f"ip_pool_list  (limit={args.limit})")

    for i, p in enumerate(pools):
        print(f"\n{SEPARATOR}")
        _print_model(p, label=f"Pool [{i}]  id={p.pool_id}  {p.pool_name!r}  {p.start_hostaddr}–{p.end_hostaddr}")  # noqa: RUF001

    if pools:
        first_id = pools[0].pool_id
        _print_section(f"ip_pool_info  pool_id={first_id}")
        with Session(host, username, password, verify=verify) as s2:
            info = s2.get(Pool, first_id)
        _print_model(info, label=f"Pool info  id={info.pool_id}  {info.pool_name!r}")

        _print_section("Cross-check: keys in list[0] vs info")
        _cross_check(pools[0], info)

    _print_section("ip_pool_count")
    _print_count(host, username, password, verify, Pool, where)

    _model_extra_summary(list(pools), "Pool")


def cmd_address(host: str, username: str, password: str, verify: bool | str, args: argparse.Namespace) -> None:
    addresses: list[IpAddress] = []
    where: str | None = None

    with Session(host, username, password, verify=verify) as s:
        if args.query:
            try:
                ipaddress.ip_address(args.query)
                where = f"hostaddr='{args.query}'"
                desc = f"hostaddr='{args.query}'"
            except ValueError:
                where = f"name like '%{args.query}%'"
                desc = f"name like '%{args.query}%'"
            addresses = s.list(IpAddress, where=where)
            _print_section(f"ip_address_list  WHERE {desc}")
            if not addresses:
                print("  (no results)")
                return
        else:
            addresses = s.list(IpAddress, limit=args.limit)
            _print_section(f"ip_address_list  (limit={args.limit})")

    for i, addr in enumerate(addresses):
        print(f"\n{SEPARATOR}")
        _print_model(addr, label=f"IpAddress [{i}]  id={addr.ip_id}  {addr.hostaddr}  {addr.name!r}")

    if addresses:
        first_id = addresses[0].ip_id
        _print_section(f"ip_address_info  ip_id={first_id}")
        with Session(host, username, password, verify=verify) as s2:
            info = s2.get(IpAddress, first_id)
        _print_model(info, label=f"IpAddress info  id={info.ip_id}  {info.hostaddr}")

        _print_section("Cross-check: keys in list[0] vs info")
        _cross_check(addresses[0], info)

    _print_section("ip_address_count")
    _print_count(host, username, password, verify, IpAddress, where)

    _model_extra_summary(list(addresses), "IpAddress")


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

    sub_pool = subparsers.add_parser("pool", help="Inspect IPv4 pools")
    sub_pool.add_argument(
        "query",
        nargs="?",
        help="Pool name substring to filter. Omit for first --limit results.",
    )
    sub_pool.add_argument("--limit", type=int, default=3, metavar="N",
                          help="Max results when no query given (default: 3).")

    sub_address = subparsers.add_parser("address", help="Inspect IPv4 addresses")
    sub_address.add_argument(
        "query",
        nargs="?",
        help="IP address (e.g. 10.0.0.1) or name substring. Omit for first --limit results.",
    )
    sub_address.add_argument("--limit", type=int, default=3, metavar="N",
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
    elif args.command == "pool":
        cmd_pool(host, username, password, verify, args)
    elif args.command == "address":
        cmd_address(host, username, password, verify, args)


if __name__ == "__main__":
    main()
