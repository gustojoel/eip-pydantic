# eip-pydantic

A typed Python SDK for the EfficientIP SolidServer REST API (v8.4). Uses httpx for transport, Pydantic v2 for models. Entry point is `Session` / `AsyncSession` (sync and async). Strict mypy + pyright typing.

## Project layout

```
src/eip_pydantic/
  __init__.py          — public exports: Session, AsyncSession, Space, Subnet, …
  class_params.py      — ClassParamDict (dict-like container for class parameters)
  client.py            — _BaseEipClient, EipClient, AsyncEipClient (HTTP transport only)
  exceptions.py        — SolidServerError, ApiError, AuthenticationError, NotFoundError
  expressions.py       — Condition, OrderByExpr, ColumnExpr, ColumnCollection (WHERE/ORDERBY builder)
  session.py           — BaseSession, Session, AsyncSession (main entry point)
  models/
    base.py            — SolidServerModel (Pydantic v2, extra="allow"), RowEnabled IntEnum
    space.py           — Space model (ip_site_list / ip_site_info)
    subnet.py          — Subnet model (ip_block_subnet_list / ip_block_subnet_info)
    pool.py            — Pool model (ip_pool_list / ip_pool_info)
    address.py         — IpAddress model (ip_address_list / ip_address_info)
    vlan_domain.py     — VlanDomain model (vlmdomain_list / vlmdomain_info)
    vlan_range.py      — VlanRange model (vlmrange_list / vlmrange_info)
    vlan.py            — Vlan model (vlmvlan_list / vlmvlan_info)
    __init__.py        — re-exports: RowEnabled, SolidServerModel, Space, Subnet
tests/
  test_client.py           — transport-layer smoke tests (respx mocking)
  test_expressions.py      — expression builder unit tests (no I/O)
  test_write.py            — write-layer + Session unit tests (respx mocking)
  test_ipam_pool.py        — Pool model unit tests
  test_ipam_address.py     — IpAddress model unit tests
  test_vlan_domain.py      — VlanDomain model unit tests
  test_vlan_range.py       — VlanRange model unit tests
  test_vlan.py             — Vlan model unit tests
  integration/
    conftest.py            — Session / AsyncSession fixtures (reads .env)
    test_ipam_subnet.py    — live integration tests via Session
scripts/
  eip_inspect.py           — CLI inspection tool (parsed model + model_extra diff + ClassParamDict fields)
```

## Tooling

- **Build**: Poetry 2.x (`poetry install`, `poetry run pytest`)
- **Type check**: `poetry run mypy src/` and `poetry run pyright` (both must pass with 0 errors)
- **Tests**: `poetry run pytest`
- **Python**: 3.13 (poetry picks it; project requires ^3.11)
- **Formatter**: autopep8 (max-line-length 120, ignore E303); isort profile "hug"
- **pyright config**: `pyrightconfig.json` at repo root sets `"typeCheckingMode": "strict"` to match VS Code Pylance

## SDK architecture

### Entry point: `Session` / `AsyncSession`

`Session` (in `session.py`) is the primary API. It owns an `EipClient` internally and exposes:

- `session.list(cls, *, where, orderby, select, offset, limit, tags, no_parent_class_param)` — list objects; auto-tracks results for flush; `where` / `orderby` accept raw strings or expression objects from `cls.c`
- `session.get(cls, pk)` — fetch by PK with identity-map cache; does NOT auto-track (call `session.add(obj)` to track for writes)
- `session.add(obj)` — explicitly track an existing object for dirty-write on flush
- `session.new(obj)` — register a new object for creation on flush
- `session.delete(obj)` — DELETE immediately (removes from cache and tracked list)
- `session.flush()` — write all pending creates/updates in tracked order
- Context manager — `__exit__` flushes (clean exit only) then closes the HTTP client

`BaseSession` holds the shared non-I/O state (`_tracked`, `_cache`, `add`, `new`). `Session` and `AsyncSession` both subclass it and add `_client` + all I/O methods.

```python
# Typical sync usage
with Session("solidserver.example.com", "admin", "secret") as s:
    subnets = s.list(Subnet, where="site_id='7'", limit=10)
    space = s.get(Space, subnets[0].site_id)   # cached after first call
    subnets[0].subnet_name = "renamed"
# flush() on clean exit → one PUT

# Using the expression builder (see § Expression builder below)
with Session("solidserver.example.com", "admin", "secret") as s:
    subnets = s.list(
        Subnet,
        where=(Subnet.c.site_id == '7') & (Subnet.c.foobar == 'baz'),
        orderby=Subnet.c.priority.asc(),
    )
    # → WHERE=(site_id='7') and (tag_network_foobar='baz')
    #    ORDERBY=tag_network_priority ASC
    #    TAGS=network.foobar&network.priority  (auto-injected)

# Typical async usage
async with AsyncSession("solidserver.example.com", "admin", "secret") as s:
    subnets = await s.list(Subnet, limit=10)
    subnets[0].subnet_name = "renamed"
```

### Model request / response protocol

Every model class participates in request dispatch via four methods on `SolidServerModel`:

- `cls.build_class_request(operation, **kwargs) -> (verb, path, params)` — classmethod, for class-level operations (`'list'`, `'info'`)
- `obj.build_request(operation, **kwargs) -> (verb, path, params)` — instance method, for object-level operations (`'create'`, `'update'`, `'delete'`, `'info'`)
- `cls.parse_response(operation, data) -> list[T] | T` — classmethod, deserialises JSON for `'list'` / `'info'`
- `obj.apply_response(operation, data)` — instance method, updates the instance after a write (`'create'` calls `finalize_creation`, `'update'` calls `mark_clean`)

Each concrete model declares its API paths as ClassVars:

```python
class Space(SolidServerModel):
    _list_path:   ClassVar[str] = "rest/ip_site_list"
    _info_path:   ClassVar[str] = "rest/ip_site_info"
    _add_path:    ClassVar[str] = "rest/ip_site_add"
    _delete_path: ClassVar[str] = "rest/ip_site_delete"
```

`Subnet` overrides `build_request` for `'create'` to inject `subnet_addr` and `subnet_prefix` (derived from the frozen `subnet: IPv4Network` field). All other operations use the `SolidServerModel` base implementations.

The Session dispatches based on the verb returned by `build_class_request` / `build_request`, so models can return non-standard verbs without Session changes.

### Typing conventions

- No `from __future__ import annotations` — targeting Python 3.11+, use native `X | Y` union syntax
- Use `typing.Self` for `__enter__` / `__aenter__` return types
- Pytest fixtures that `yield` must declare `-> Iterator[T]` (from `collections.abc`)
- All helpers that don't need `self` state should be `@staticmethod` on the class; no module-level helper functions

### Model base class (`SolidServerModel`)

`SolidServerModel` (in `models/base.py`) provides:

- Pydantic v2 config: `extra="allow"` (unknown fields stored in `model_extra`), `populate_by_name=True`, `str_strip_whitespace=True`, `validate_assignment=True`
- `errno: int | None` — present on every API row (not just mutation responses), frozen
- `_class_param_prefix: ClassVar[str | None]` — set by subclasses to enable class-param properties
- `tags_prefix: ClassVar[str]` — TAGS object-type name for the expression builder (e.g. `"site"`, `"network"`); empty string means no TAGS support
- `_pk_field: ClassVar[str]` — name of the PK field (e.g. `"site_id"`, `"subnet_id"`)
- `_list_path`, `_info_path`, `_add_path`, `_delete_path: ClassVar[str]` — API paths (set by each model)
- `c: ClassVar[ColumnCollection]` — expression-builder accessor; see § Expression builder
- Forward-coercion helpers (wire → Python, used by `model_validator`s):
  - `_as_str(v)` — `""` / `"#"` → `None`
  - `_as_int(v)` — string → `int | None`
  - `_as_nz_int(v)` — like `_as_int` but `"0"` → `None` (FK null sentinel)
  - `_as_float(v)` — string → `float | None`
  - `_as_bool(v)` — `"1"` → `True`, `"0"` → `False`, `""` / `None` → `None`
  - `_as_hex_ipv4(v)` — 8-char hex (`"0a541400"`) → `IPv4Address | None`
  - `_as_dotted_ipv4(v)` — dotted-decimal (`"10.84.20.0"`) → `IPv4Address | None`
  - `_as_datetime(v)` — Unix epoch string → UTC `datetime`
- Reverse-coercion statics (Python → wire): `_to_bool_str(v)`, `_to_int_str(v)`
- Write-layer methods: `write_params()`, `build_class_request()`, `build_request()`, `parse_response()`, `apply_response()`, `mark_clean()`, `mark_new()`, `finalize_creation()`, `assign_id()`
- Properties: `id`, `id_filter`, `is_dirty`, `is_new`, `tagged_class_parameters`
- Class parameters are stored as `ClassParamDict` fields on each model (e.g. `Space.class_params`, `Space.parent_site_class_params`); there are no separate `class_parameters` / `class_parameters_properties` / `class_parameters_inheritance_source` properties on `SolidServerModel`

### Per-model coercion pattern

Each model (e.g. `Subnet`) owns its own `@model_validator(mode="before")` that handles all wire-format → Python-type coercion explicitly. Use a `match` statement with OR-patterns to group fields by coercion type:

```python
@model_validator(mode="before")
@classmethod
def _coerce(cls, data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    v = cast(dict[str, Any], data)
    out: dict[str, Any] = {}
    for key, val in v.items():
        match key:
            case "start_ip_addr" | "end_ip_addr":
                out[key] = cls._as_ipv4(val)
            case "subnet_id" | "subnet_size":
                out[key] = cls._as_int(val)
            case "parent_subnet_id" | "vlmdomain_id":
                out[key] = cls._as_nz_int(val)   # "0" = not set
            case _:
                out[key] = cls._as_str(val) if key in cls.model_fields else val
    return out
```

The `_` fallback strips `""` / `"#"` sentinels from declared `str` fields and passes unknown extras (e.g. `tag_*` fields from TAGS queries) through unchanged.

### Expression builder (`expressions.py`)

`Session.list()` accepts raw SQL-style strings **or** typed expression objects built via `Model.c.<field>`.  The expression builder (in `expressions.py`) provides three public types:

| Type | Role |
|---|---|
| `Condition` | Serialisable WHERE expression; produced by comparison operators on `ColumnExpr` |
| `OrderByExpr` | Serialisable ORDER BY expression; produced by `.asc()` / `.desc()` on `ColumnExpr` |
| `ColumnExpr` | A column reference; produced by `Model.c.<field_name>` |

**`Model.c` accessor** — each model class has a `c: ClassVar[ColumnCollection]` attribute.  Accessing `Model.c.field_name` checks `model_fields`:

- Field declared on the model → `ColumnExpr('field_name')` (no TAGS requirement)
- Unknown name → `ColumnExpr('tag_{prefix}_{name}', required_tags={'prefix.name'})` where `prefix = Model.tags_prefix`

**TAGS auto-injection** — `Session.list()` collects `required_tags` from any `Condition` / `OrderByExpr` passed as `where` / `orderby` and merges them (joined by `&`) into the `TAGS` query parameter before building the request.  Explicit `tags=` strings are appended.

**Operator → wire string mapping:**

```python
Subnet.c.subnet_name == 'prod'          # subnet_name='prod'
Subnet.c.subnet_name != 'legacy'        # subnet_name!='legacy'
Subnet.c.subnet_size >= 128             # subnet_size>='128'
Subnet.c.subnet_name.like('%prod%')     # subnet_name like '%prod%'
Subnet.c.site_id.in_(['1','2'])         # site_id in ('1', '2')
Subnet.c.subnet_class_name.is_null()    # subnet_class_name=''

# Tagged class parameter (unknown field name)
Subnet.c.foobar == 'baz'               # tag_network_foobar='baz'  + TAGS=network.foobar
Space.c.rank.desc()                     # tag_site_rank DESC        + TAGS=site.rank

# Combining
(Subnet.c.site_id == '7') & (Subnet.c.foobar == 'baz')
# → (site_id='7') and (tag_network_foobar='baz')   TAGS=network.foobar

(Space.c.site_name == 'prod') | (Space.c.site_name == 'staging')
# → (site_name='prod') or (site_name='staging')   (no TAGS)
```

**Adding a new model** — set `tags_prefix` to the correct TAGS object-type name from the API reference table (§ TAGS, "TAGS object-type names"):

```python
class IpAddress(SolidServerModel):
    tags_prefix: ClassVar[str] = "ip"   # from the TAGS table
    ...
```

Values are always coerced to `str` and single-quoted; internal `'` is escaped as `''`.

### `RowEnabled` enum

`RowEnabled(IntEnum)` in `models/base.py`: `DELETED=0`, `ENABLED=1`, `UNMANAGED=2`. Used for the `row_enabled` field present on all SolidServer objects.

## Live API findings (ip_block_subnet_*)

- `errno: "0"` is included in every row of `*_list` and `*_info` responses (not only mutation responses).
- `ip_block_subnet_list` does **not** return `site_class_parameters`, `site_class_parameters_properties`, `parent_subnet_class_parameters`, or `parent_subnet_class_parameters_properties` — these are only present in `ip_block_subnet_info` responses. The `_coerce` validator on `Subnet` handles both: `site_class_params` and `parent_subnet_class_params` (`ClassParamDict | None`) default to an empty/missing dict when the blobs are absent.
- `start_ip_addr` / `end_ip_addr` come back as 8-char hex strings; `start_hostaddr` / `end_hostaddr` come as dotted-decimal — both are consumed by `_coerce` to build the `subnet: IPv4Network` field (stored) and `start_ip_addr` / `end_ip_addr` properties. `parent_start_ip_addr` / `parent_end_ip_addr` also arrive as hex and are stored directly.
- FK-style ID fields (`parent_subnet_id`, `vlmdomain_id`, etc.) use `"0"` to mean "not set" — use `_as_nz_int` for these.
- `subnet_level` uses `"0"` to mean "block type" (not "not set") — use plain `_as_int`.

## `scripts/eip_inspect.py`

Ad-hoc inspection tool. Reads credentials from `.env` (same as integration tests). Uses subcommands to select object type. Prints the parsed model fields (excluding `ClassParamDict` entries), any `model_extra` keys (fields the API returns that our model doesn't declare yet), non-empty `ClassParamDict` fields by name, and `tagged_class_parameters`.

```
poetry run python scripts/eip_inspect.py subnet                     # first 3 subnets
poetry run python scripts/eip_inspect.py subnet 10.84.20.0/24       # lookup by CIDR
poetry run python scripts/eip_inspect.py subnet prod-dmz            # lookup by name substring
poetry run python scripts/eip_inspect.py subnet --limit 10          # first 10 subnets

poetry run python scripts/eip_inspect.py space                      # first 3 spaces
poetry run python scripts/eip_inspect.py space prod                 # lookup by name substring

poetry run python scripts/eip_inspect.py pool                       # first 3 pools
poetry run python scripts/eip_inspect.py pool dhcp-range            # filter by pool name substring

poetry run python scripts/eip_inspect.py address                    # first 3 addresses
poetry run python scripts/eip_inspect.py address 10.84.20.5         # lookup by IP
poetry run python scripts/eip_inspect.py address gateway            # filter by name substring
```

Each subcommand also runs `*_info` on the first result and cross-checks the key sets between list and info responses, then prints a count.

---

## SolidServer REST API — Reference Summary

### URL structure

```
https://<host>/rest/<service>?<params>    # for the 5 key service types
https://<host>/rpc/<service>?<params>     # for all other (non-CRUD) services
```

The current `_httpx_kwargs` sets `base_url = f"https://{host}/"` (no `/rest/` prefix), so callers must include `rest/` or `rpc/` in the path argument.

### Authentication

Three options (all require HTTPS — http returns 302):

1. **Basic auth** — username:password (what we use via `httpx.BasicAuth`)
2. **Header-based** — `X-IPM-Username: <base64>` + `X-IPM-Password: <base64>`
3. **API token** — `X-SDS-TS: <epoch>` + `Authorization: SDS <token-id>:<SHA3-256-signature>`
   - Signature = SHA3-256 of `"<secret>\n<epoch>\n<METHOD>\n<full-url>"`)

### HTTP verb → service type mapping

| Verb     | Service type            | Notes                        |
|----------|-------------------------|------------------------------|
| POST     | `*_add`                 | Create (not idempotent)      |
| PUT      | `*_add` (with ID)       | Edit existing (idempotent)   |
| GET      | `*_list`, `*_info`, `*_count` | Read (idempotent)    |
| DELETE   | `*_delete`              | Delete (idempotent)          |
| OPTIONS  | any                     | Help/introspection           |

PATCH is **not** supported. Operations apply to **one object at a time**.

### The 5 key service types (all under `/rest/`)

| Suffix      | Purpose                                  |
|-------------|------------------------------------------|
| `*_add`     | Add (POST) or edit (PUT) one object      |
| `*_list`    | List all objects                         |
| `*_info`    | Get one specific object (same output as list) |
| `*_count`   | Count objects matching WHERE             |
| `*_delete`  | Delete one object                        |

Additional service types found in many modules:
- `*_groupby` / `*_groupby_count` — SQL-style GROUP BY aggregation
- `ip_find_free_subnet`, `ip_find_free_address` — find next available resource
- `group_*_add` / `group_*_delete` — manage which user-groups can access an object

### Query parameters for `*_list` / `*_info`

| Parameter            | Description                                                  |
|----------------------|--------------------------------------------------------------|
| `SELECT`             | Comma-separated list of columns to return                    |
| `WHERE`              | SQL-style filter (e.g. `site_name='prod'`)                   |
| `ORDERBY`            | Sort clause (e.g. `site_name ASC`)                           |
| `offset`             | Rows to skip (lowercase required)                            |
| `limit`              | Max rows to return (lowercase required)                      |
| `NO_PARENT_CLASS_PARAM` | Exclude parent object's class parameters from output      |
| `TAGS`               | Tag class parameters (see TAGS section below)                |

All clause values must be URL-encoded. `WHERE`/`ORDERBY`/`SELECT` keywords are case-sensitive (uppercase).

### `add_flag` parameter (on all `*_add` services)

| Value       | Behaviour                                    |
|-------------|----------------------------------------------|
| `new_edit`  | Default — create if absent, edit if present  |
| `new_only`  | Fail if object already exists                |
| `edit_only` | Fail if object does not exist                |

### Common output for `*_add` / `*_delete`

```json
{
  "errno": "0",          // "0" = success; other values = error code
  "errmsg": "...",
  "severity": "Notice",  // Notice | Warning | Error
  "parameters": "...",   // which input param caused the problem
  "param_format": "...",
  "param_value": "...",
  "ret_oid": "42"        // DB ID of added/edited object (*_add only)
}
```

### Data type gotchas

- **All JSON values are strings** — even integers and booleans. Parse accordingly.
- **IP addresses are often hex-encoded** in output (e.g. `"0d000000"` for `13.0.0.0`).
- **`row_enabled`**: `"0"` = deleted/ignored, `"1"` = enabled, `"2"` = unmanaged/disabled.
- **Class parameters** are concatenated URL-encoded strings: `key1=val1&key2=val2`.

---

## TAGS — custom class parameters (Chapter 4)

TAGS is EfficientIP's mechanism for accessing *class parameters* — arbitrary user-defined key/value metadata attached to any object. Without TAGS, class params are returned as one big concatenated string (`site_class_parameters = "foo=bar&baz=qux"`). With TAGS, you extract individual ones as first-class fields.

**Only works on `*_list` and `*_info` services.**

### Tagging a class parameter

```
GET /rest/ip_site_list?TAGS=site.my_param
```

This adds `tag_site_my_param` as an extra field in every row of the response.

Multiple tags: the `&` separating them must be URL-encoded inside the TAGS value:
```
?TAGS=site.param1%26site.param2
```

### Using tagged params in WHERE

```
?TAGS=dhcpscope.information&WHERE=tag_dhcpscope_information%20like%20%27important%27
# readable: WHERE = tag_dhcpscope_information like 'important'
```

String comparison: `like 'value'` or `like '%partial%'` (% = wildcard, encoded as %25)
Integer comparison: `='42'` (= encoded as %3D)
Multiple conditions with `and` / `or`.

### Using tagged params in ORDERBY

```
?TAGS=site.priority&ORDERBY=tag_site_priority%20DESC
```

### Using tagged params in SELECT / GROUPBY (for `*_groupby` services)

```
?TAGS=dhcpscope.info&SELECT=count(*)%2Ctag_dhcpscope_info&GROUPBY=tag_dhcpscope_info
```

Aggregation functions: `count`, `max`, `min`, `sum`, `avg`. Use `count(*)` to count rows.

### TAGS object-type names (database table names)

| Module          | Object                | TAGS type      |
|-----------------|----------------------|----------------|
| IPAM            | Space                | `site`         |
| IPAM            | IPv4 Network         | `network`      |
| IPAM            | IPv6 Network         | `network6`     |
| IPAM            | IPv4 Pool            | `pool`         |
| IPAM            | IPv6 Pool            | `pool6`        |
| IPAM            | IPv4 Address         | `ip`           |
| IPAM            | IPv6 Address         | `ip6`          |
| DHCP            | Server (v4)          | `dhcp`         |
| DHCP            | Server (v6)          | `dhcp6`        |
| DHCP            | Scope (v4)           | `dhcpscope`    |
| DHCP            | Scope (v6)           | `dhcpscope6`   |
| DHCP            | Group (v4)           | `dhcpgroup`    |
| DHCP            | Group (v6)           | `dhcpgroup6`   |
| DHCP            | Range (v4)           | `dhcprange`    |
| DHCP            | Range (v6)           | `dhcprange6`   |
| DHCP            | Static (v4)          | `dhcphost`     |
| DHCP            | Static (v6)          | `dhcphost6`    |
| DNS             | Server               | `dns`          |
| DNS             | Zone                 | `dnszone`      |
| DNS             | View                 | `dnsview`      |
| NOM             | Folder               | `nomfolder`    |
| NOM             | Network Object       | `nomnetobj`    |
| NetChange       | Network Device       | `iplnetdev`    |
| NetChange       | Port                 | `iplport`      |
| Workflow        | Request              | `request`      |
| Device Manager  | Device               | `hostdev`      |
| Device Manager  | Port/Interface       | `hostiface`    |
| VLAN Manager    | Domain               | `vlmdomain`    |
| VLAN Manager    | Range                | `vlmrange`     |
| VLAN Manager    | VLAN                 | `vlmvlan`      |
| VRF             | VRF                  | `vrfobject`    |
| Administration  | Group of users       | `grp`          |
| Administration  | User                 | `usr`          |

---

## API modules overview (Parts II–XIV)

### Part II — IPAM (Chapters 5–13)

Hierarchy: **Space** → **Network** (block/subnet, VLSM tree) → **Pool** → **Address**

| Chapter | Object             | Key services                                         |
|---------|--------------------|------------------------------------------------------|
| 5       | Space              | `ip_site_*`                                          |
| 6       | IPv4 Network       | `ip_subnet_add`, `ip_block_subnet_list/info/count`, `ip_find_free_subnet`, `ip_block_subnet_groupby*` |
| 7       | IPv6 Network       | `ip6_subnet6_add`, `ip6_block6_subnet6_*`            |
| 8       | IPv4 Pool          | `ip_pool_*`                                          |
| 9       | IPv6 Pool          | `ip6_pool6_*`                                        |
| 10      | IPv4 Address       | `ip_add`, `ip_address_list/info/count`, `ip_find_free_address`, `ip_free_address_list`, `ip_used_address_list`, `ip_address_groupby*`, `ip_delete` |
| 11      | IPv6 Address       | `ip6_address6_*`                                     |
| 12      | IPv4 Alias         | `ip_alias_*`                                         |
| 13      | IPv6 Alias         | `ip6_alias_*`                                        |

Notable IPAM quirks:
- Networks use `ip_block_subnet_list` (not `ip_subnet_list`) — both blocks and subnets in one call.
- `subnet_level=0` is mandatory to create a block-type network.
- `ip_subnet_add` is used for both blocks and subnets (distinguished by `subnet_level`).
- VLSM: networks form a tree; spaces can also be nested.

### Part III — DHCP (Chapters 14–32)

DHCPv4 and DHCPv6 mirrors. Hierarchy: **Server** → **Shared Network** → **Scope** → **Range** / **Static**

Key chapters: servers (14/15), shared networks (16/17), scopes (18/19), groups (20/21), ranges (22/23), leases (24/25), statics (26/27), options (28/29), ACLs (30/31), failover (32).

### Part IV — DNS (Chapters 33–39)

Hierarchy: **Server** → **View** → **Zone** → **Resource Record**

Chapters: servers (33), views (34), zones (35), RRs (36), ACLs (37), TSIG keys (38), DNSSEC (39).
DNS zones and views have `*_param_add/list/info/count/delete` sub-services for BIND parameters.

### Parts V–XIII — Other modules

| Part | Module                   | Prefix(es)       |
|------|--------------------------|------------------|
| V    | Network Object Manager   | `nom_`           |
| VI   | Application              | `app_`           |
| VII  | Guardian                 | `guardian_`      |
| VIII | Cloud Observer           | `co_`            |
| IX   | NetChange                | `iplnetdev*`, `iplport*`, `iplnetdevroute*`, `iplnetdevvlan*`, `ipldev*`, `iplnetdevaddr*` |
| X    | Workflow                 | `workflow_request_add`, `request_incoming_*`, `request_outgoing_*` |
| XI   | Device Manager           | `hostdev_*`, `hostiface_*`, `link_hostiface_*` |
| XII  | VLAN Manager             | `vlm_*`, `vlmdomain*`, `vlmrange*`, `vlmvlan*` |
| XIII | VRF                      | `vrf_*`, `vrfobject*`, `link_vrfimportexport*` |

### Part XII — VLAN Manager (Chapters 64–66)

Hierarchy: **VlanDomain** → **VlanRange** → **Vlan**

| Chapter | Object      | Key services                              | Model        |
|---------|-------------|-------------------------------------------|--------------|
| 64      | Domain      | `vlm_domain_add`, `vlmdomain_list/info/count/delete` | `VlanDomain` |
| 65      | Range       | `vlm_range_add`, `vlmrange_list/info/count/delete`   | `VlanRange`  |
| 66      | VLAN        | `vlm_vlan_add`, `vlmvlan_list/info/count/delete`     | `Vlan`       |

Notable VLAN Manager quirks:
- **Add verb vs list prefix**: creation uses `vlm_domain_add` / `vlm_range_add` / `vlm_vlan_add` (underscore after `vlm`), but list/info/count/delete use `vlmdomain_*` / `vlmrange_*` / `vlmvlan_*` (no underscore).
- **`support_vxlan`** on `VlanDomain`: `"Can be edited: No"` — frozen after creation; serialised as `"1"`/`"0"` via `_to_bool_str` for new objects.
- **`vlmvlan_vlan_id` alias**: the Pydantic field is `vlan_id` (Python name) with `alias="vlmvlan_vlan_id"` (wire name). A `vlmvlan_vlan_id` property provides backward-compatible access. `write_params()` uses the alias when serialising.
- **`type` field on `Vlan`**: `"used"` for assigned VLANs, `"free"` for unassigned spans (which carry `free_start_vlan_id` / `free_end_vlan_id` instead of a VLAN name).
- **`vlmrange_id` in Vlan**: uses `_as_nz_int` — `"0"` means the VLAN is not inside a range.
- **`vlmrange_row_enabled`** on `Vlan`: present in API output but not in API documentation; stored as `str | None`.
| XIV  | Administration           | `service_*`, `group_*`, `user_*`, `custom_db_data_*`, `config_*` |

---

## Implementation notes

- **`/rest/` vs `/rpc/`**: the base URL is set to `https://<host>/` (no path prefix). The path passed to `client.get(path)` must include `rest/` or `rpc/`. The 5 key service types always use `rest/`; everything else uses `rpc/`.
- **Payload**: POST and PUT can send params as JSON body instead of query string. GET, DELETE, OPTIONS cannot.
- **Class parameters inheritance**: objects can `inherit`, `set`, or `inherited_or_set` class params from containers; propagation can be `restrict` or `propagate`.
- **`validate_warnings`**: pass `accept` to bypass warning-level Guardian rules.
- **`class_parameters_to_delete`**: URL-encoded list of class param names to remove on edit.
