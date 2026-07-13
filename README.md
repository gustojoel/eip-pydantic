# eip-pydantic

[![PyPI version](https://img.shields.io/pypi/v/eip-pydantic.svg)](https://pypi.org/project/eip-pydantic/)
[![Python versions](https://img.shields.io/pypi/pyversions/eip-pydantic.svg)](https://pypi.org/project/eip-pydantic/)
[![Tests](https://github.com/dataway/eip-pydantic/actions/workflows/tests.yml/badge.svg)](https://github.com/dataway/eip-pydantic/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/dataway/eip-pydantic/graph/badge.svg)](https://codecov.io/gh/dataway/eip-pydantic)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

`eip-pydantic` is a Python package for the [EfficientIP SolidServer](https://www.efficientip.com/products/solidserver-ddi/) REST API which leans heavily on Pydantic.

Here's how it differs from other packages in the EfficientIP space:

- Based on Pydantic: all EfficientIP objects are mapped to Pydantic models, making it easy to integrate into existing Pydantic based systems (e.g. FastAPI)
- Both async/await and sync styles supported
- Unit-of-work pattern inspired by SQLAlchemy
- Expression builder for filter and sort clauses inspired by SQLAlchemy
- Full type annotations, passes pyright and mypy

## Quick Example

### Synchronous

```python
from eip_pydantic import Session
from eip_pydantic.models import IpAddress, RowEnabled, Subnet

with Session("solidserver.example.com", "admin", "secret") as session:
    # Three conditions AND-ed together: an ordinary field, a LIKE pattern, and
    # a custom class parameter ("environment") — the last of which requires no
    # special handling on your part, see "The expression builder" below.
    where = (
        (Subnet.c.site_id == "7")
        & (Subnet.c.subnet_name.like("%app-tier%"))
        & (Subnet.c.environment == "production")
    )
    subnet = session.one(Subnet, where=where)

    # Pydantic has already done real work parsing this row:
    print(subnet.subnet)          # IPv4Network('10.20.1.0/24') — decoded from wire-format hex
    print(subnet.subnet_level)    # int, not the wire's "1" string
    print(subnet.row_enabled is RowEnabled.ENABLED)  # a real enum, safely comparable — not a raw code
    print(subnet.parent_subnet_id)  # None if this is a top-level block ("0" on the wire)

    # subnet_id is frozen — the server assigns it, so mutating it is a bug we
    # want to catch immediately rather than on the next flush():
    try:
        subnet.subnet_id = 999999
    except Exception as exc:
        print(f"rejected as expected: {exc.__class__.__name__}")

    # Find a free address inside the subnet we just looked up.
    candidates = session.find_free_address(subnet=subnet, max_find=1)
    free_ip = candidates[0]

    # Register the candidate IP.
    new_host = session.create(
        IpAddress, subnet,
        hostaddr=str(free_ip.ip_addr),
        name="auto-provisioned",
        class_params={"environment": "production"},
    )
    session.flush()  # one POST; new_host.ip_id is now populated

    print(f"claimed {new_host.hostaddr} as {new_host.name} (id={new_host.ip_id})")
```

### Asynchronous

```python
import asyncio

from eip_pydantic import AsyncSession
from eip_pydantic.models import IpAddress, Subnet


async def main() -> None:
    async with AsyncSession("solidserver.example.com", "admin", "secret") as session:
        where = (
            (Subnet.c.site_id == "7")
            & (Subnet.c.subnet_name.like("%app-tier%"))
            & (Subnet.c.environment == "production")
        )
        subnet = await session.one(Subnet, where=where)

        candidates = await session.find_free_address(subnet=subnet, max_find=1)
        free_ip = candidates[0]

        new_host = session.create(
            IpAddress, subnet,
            hostaddr=str(free_ip.ip_addr),
            name="auto-provisioned",
            class_params={"environment": "production"},
        )
        await session.flush()

        print(f"claimed {new_host.hostaddr} as {new_host.name} (id={new_host.ip_id})")


asyncio.run(main())
```

## Design philosophy

If you have used [SQLAlchemy](https://www.sqlalchemy.org/), the shape of this library will feel familiar. SolidServer's REST API is not a database, but it exposes a similar hierarchical, relational structure — spaces contain networks, networks contain pools and addresses, each object has a primary key, and objects reference each other by foreign key. `eip-pydantic` borrows three ideas from SQLAlchemy's ORM to make working with that structure pleasant:

| SQLAlchemy | eip-pydantic | Purpose |
|---|---|---|
| `Session` | `Session` / `AsyncSession` | Unit-of-work object: tracks loaded objects, batches writes, exposes `flush()` |
| `session.query(Model).filter(...)` | `session.list(Model, where=...)` | Typed queries against a collection endpoint |
| `Model.column == value` | `Model.c.field == value` | Column expressions that build filter clauses instead of evaluating immediately |
| Identity map | `session.get(cls, pk)` | Only one Python object per `(class, primary key)` pair per session |
| `Base` declarative class | `SolidServerModel` | Common base class handling (de)serialization and dirty tracking |

## Installation

```bash
pip install eip-pydantic
```

Requires Python 3.11 or newer. The only runtime dependencies are `httpx` and `pydantic` (v2).


## Core concepts

### Models

Every SolidServer object type — `Space`, `Subnet`, `Pool`, `IpAddress`, `DnsZone`, `DhcpScope`, `Vlan`, and more — is a Pydantic model subclassing `SolidServerModel`. Fields are typed and coerced automatically from SolidServer's string-typed wire format: IP addresses (including the hex-encoded ones) become `ipaddress.IPv4Address` / `IPv4Network`, integers and booleans are parsed properly, timestamps become timezone-aware `datetime` objects, unset foreign keys (`"0"` on the wire) become `None`, and fields the server marks read-only — primary keys, trace/audit fields — are declared `frozen=True`, so assigning to them raises a `pydantic.ValidationError` immediately at the point of the mistake rather than failing later on `flush()`. All of this is visible in the Quickstart example above.

### `Session` is a unit of work

`Session.list()`, `.get()`, `.one()`, and `.one_or_none()` fetch objects and automatically register them for change tracking. Nothing is sent to the server until you call `flush()` — or exit a `with` block cleanly, which calls it for you. `session.get(cls, pk)` additionally maintains an identity map, so repeated lookups of the same object within a session never issue a second HTTP request:

```python
with Session(host, user, password) as session:
    space = session.one(Space, where=Space.c.site_name == "production")
    space.site_description = "Primary production IPAM space"
    # still just an attribute assignment — no HTTP request yet

    same_space = session.get(Space, space.site_id)
    assert same_space is space  # identity map: same Python object, no second request

# flush() ran on exit: exactly one PUT request for the one dirty object
```

### Creating (and deleting) a hierarchy

`session.create()` constructs a new model instance and registers it for a `POST` on the next `flush()`. Passing a `parent=` object automatically injects the correct foreign key field — you never have to remember whether a `Subnet` wants `site_id` or `parent_subnet_id` — and objects are flushed in the order they were registered, so a child's parent-id field is filled in automatically once the parent itself has been assigned a server-side id:

```python
from ipaddress import IPv4Network

with Session(host, user, password) as session:
    space = session.get(Space, 7)

    block = session.create(
        Subnet, space,
        subnet_name="prod-block",
        subnet=IPv4Network("10.0.0.0/16"),
        subnet_level=0,
    )  # space.site_id was injected automatically

    dmz = session.create(
        Subnet, block,
        subnet_name="prod-dmz",
        subnet=IPv4Network("10.0.1.0/24"),
        subnet_level=1,
    )  # block.parent_subnet_id will be injected once `block` itself has an id

    session.flush()
    # block is POSTed first (registration order), then dmz — by which point
    # block.subnet_id exists and was filled into dmz automatically
    print(block.subnet_id, dmz.subnet_id)

    # Deletes are not batched: this issues the DELETE immediately and drops
    # the object from the identity cache and the tracked list.
    stale = session.one(Subnet, where=Subnet.c.subnet_name == "decommissioned")
    session.delete(stale)
```

`session.new(obj)` registers a manually constructed model instance the same way `create()` does, and `session.add(obj)` tracks an already-loaded object for writes without requiring it came from `list()`/`get()`.

## The expression builder

Every model class exposes a `.c` accessor (short for "columns", mirroring SQLAlchemy's `Table.c`) that produces typed column expressions. Comparing a column expression against a value builds a `Condition` — a small, immutable object that serializes to the SolidServer `WHERE`-clause syntax and does nothing until it's passed to `list()`, `one()`, `count()`, or similar. `Condition` objects compose with `&` / `|` exactly like SQLAlchemy's `and_()` / `or_()`, and `.asc()` / `.desc()` build an `OrderByExpr` the same way:

```python
from eip_pydantic.models import Subnet

Subnet.c.subnet_name == "prod-dmz"          # subnet_name='prod-dmz'
Subnet.c.subnet_name != "legacy"            # subnet_name!='legacy'
Subnet.c.subnet_size >= 128                 # subnet_size>='128'
Subnet.c.subnet_name.like("%prod%")         # subnet_name like '%prod%'
Subnet.c.site_id.in_(["1", "2", "3"])       # site_id in ('1', '2', '3')
Subnet.c.subnet_class_name.is_null()        # subnet_class_name=''

session.list(
    Subnet,
    where=(Subnet.c.site_id == "7") & (Subnet.c.subnet_name.like("%prod%")),
    orderby=Subnet.c.subnet_name.asc(),
)
```

`where` and `orderby` both also accept a raw string if you'd rather write the clause yourself (`session.list(Subnet, where="site_id='7'")`) — typed expressions and raw strings can be mixed freely.

### Why bother with the expression builder?

Beyond avoiding string concatenation bugs, the expression builder understands SolidServer-specific wire encodings and applies them automatically — as seen in the Quickstart example's `Subnet.c.environment == "production"` condition, which required no special syntax even though `environment` isn't a declared field at all. Any attribute accessed via `.c` that isn't a declared field is assumed to be a custom class parameter: the correct `tag_network_environment='production'` condition is built, and the `TAGS=network.environment` query parameter that SolidServer requires for tag-based filtering is collected from the whole expression tree and injected into the request automatically. You never have to compute it yourself.

The same automatic handling applies to two other SolidServer-specific wire encodings:

```python
from ipaddress import IPv4Address, IPv4Network

# Hex-encoded IPv4 columns (start_ip_addr, end_ip_addr, ...) accept an
# IPv4Address, a dotted string, or raw hex — and always compare correctly:
Subnet.c.start_ip_addr == IPv4Address("10.0.0.1")   # start_ip_addr='0a000001'
Subnet.c.start_ip_addr >= "10.0.0.10"                # start_ip_addr>='0a00000a'

# Subnet.c.subnet is a single Python attribute (an IPv4Network), but on the
# wire a network is a *pair* of hex-encoded start/end addresses — comparing
# against it produces the correct compound condition automatically:
Subnet.c.subnet == IPv4Network("10.16.1.0/24")
# (start_ip_addr='0a100100') and (end_ip_addr='0a1001ff')
```

## Class parameters

Class parameters — SolidServer's mechanism for attaching arbitrary key/value metadata to any object — are accessible as a typed, dict-like container on every model: `ClassParamDict`. It behaves like a `dict[str, str]` for reading and writing, while separately tracking each key's inheritance mode (`set`, `inherited`, `inherited_or_set`) and propagation mode (`propagate`, `restrict`):

```python
subnet.class_params["environment"]              # "production"
subnet.class_params["environment"] = "staging"   # marks the object dirty, ready for flush()

subnet.class_params.is_set("environment")        # True — explicitly set here
subnet.class_params.is_restrict("environment")   # False — propagates to child objects

# Explicit control over inheritance/propagation, rather than the defaults above:
subnet.class_params.set("owner", "network-team", inherited_or_set=False, restrict=True)

del subnet.class_params["environment"]  # staged for deletion on next flush()
```

Class parameters can also be set at creation time as a plain dict, exactly as shown in the Quickstart example's `class_params={"environment": "production"}`.

## Error handling

All exceptions raised by the SDK derive from `SolidServerError`:

```python
from eip_pydantic import ApiError, AuthenticationError, NotFoundError, SolidServerError

try:
    with Session(host, user, password) as session:
        session.get(Subnet, 999999)
except NotFoundError as exc:
    print(f"not found: {exc.status_code} {exc.message}")
except AuthenticationError:
    print("check credentials")
except ApiError as exc:
    print(f"API error: {exc.status_code} {exc.message}")
except SolidServerError:
    print("some other SDK error")
```

If a `flush()` fails partway through a batch of writes, the session is reset and every tracked object is marked invalidated — further attempts to read or mutate them raise `InvalidatedError`, so a partially-written unit of work cannot be mistaken for a consistent one. `session.last_flush` records exactly which writes succeeded before the failure for post-mortem inspection.

## Author


## License

Released under the [MIT License](LICENSE).
