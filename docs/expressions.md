# Expression Builder

`eip_pydantic.expressions` provides a typed, composable API for building the
`WHERE`, `ORDERBY`, and `TAGS` parameters that the SolidServer REST API accepts on
`*_list`, `*_info`, and `*_count` endpoints.

Instead of writing raw strings like `"site_id='7' and subnet_name like '%prod%'"`,
you write Python expressions that are type-checked, autocompleted, and automatically
inject the `TAGS` parameter when tagged class parameters are involved:

```python
subnets = s.list(
    Subnet,
    where=(Subnet.c.site_id == "7") & Subnet.c.subnet_name.like("%prod%"),
    orderby=Subnet.c.subnet_name.asc(),
)
```

Raw strings still work everywhere and are never deprecated — the builder is opt-in.

---

## Core concepts

### `ColumnExpr` — a column reference

`ColumnExpr` represents one API column.  You never construct it directly;
instead, access it through the `Model.c` class attribute:

```python
Subnet.c.subnet_name    # ColumnExpr for the 'subnet_name' column
Subnet.c.foobar         # ColumnExpr for a tagged class parameter 'foobar'
```

Applying a comparison operator to a `ColumnExpr` returns a `Condition`.
Calling `.asc()` or `.desc()` returns an `OrderByExpr`.

### `Condition` — a serialisable WHERE clause

`Condition` carries the wire-format string (e.g. `"site_id='7'"`) together
with a set of TAGS strings required for the clause to be evaluated.
`Session.list()` calls `str(condition)` for the `WHERE` parameter and merges
`condition.required_tags` into the `TAGS` parameter automatically.

Conditions are immutable and composable with `&` and `|`.

### `OrderByExpr` — a serialisable ORDER BY clause

`OrderByExpr` carries the wire-format string (e.g. `"subnet_name ASC"`)
plus any required TAGS.  Passed as `orderby=` to `Session.list()`.

---

## The `Model.c` accessor

Each model class exposes `.c` as a `ColumnCollection` bound to that class.

```python
Space.c.site_name       # declared field  → ColumnExpr('site_name')
Subnet.c.site_id        # declared field  → ColumnExpr('site_id')
Subnet.c.foobar         # unknown name    → ColumnExpr('tag_network_foobar',
                        #                               required_tags={'network.foobar'})
Space.c.rank            # unknown name    → ColumnExpr('tag_site_rank',
                        #                               required_tags={'site.rank'})
```

**Dispatch rules:**

- If the name matches a declared `model_fields` key on the model, it is a
  *real field* — the wire name is the field name as-is, no TAGS are needed.
- Otherwise it is treated as a *tagged class parameter*: the wire name becomes
  `tag_{tags_prefix}_{name}`, and `{tags_prefix}.{name}` is added to the
  required-TAGS set.  `tags_prefix` is a `ClassVar` on each model (e.g.
  `"network"` for `Subnet`, `"site"` for `Space`, `"ip"` for `IpAddress`).

`dir(Model.c)` returns the list of declared field names, enabling IDE
autocompletion for real fields.

---

## Operators

All values are coerced to `str()` and wrapped in single quotes.  Internal
single quotes are doubled (`O'Brien` → `'O''Brien'`).

### Equality and comparison

```python
Subnet.c.site_id == "7"          # site_id='7'
Subnet.c.site_id != "7"          # site_id!='7'
Subnet.c.subnet_size < 256       # subnet_size<'256'  (int coerced to str)
Subnet.c.subnet_size <= 256      # subnet_size<='256'
Subnet.c.subnet_size > 0         # subnet_size>'0'
Subnet.c.subnet_size >= 128      # subnet_size>='128'
```

### Pattern matching

`%` is the wildcard character (SolidServer uses SQL-style LIKE semantics):

```python
Subnet.c.subnet_name.like("%prod%")    # subnet_name like '%prod%'
Subnet.c.subnet_name.like("prod-%")   # subnet_name like 'prod-%'
```

### Set membership

```python
Subnet.c.site_id.in_(["1", "2", "7"])
# → site_id in ('1', '2', '7')
```

### NULL / empty check

The SolidServer API represents NULL as an empty string `""`:

```python
Subnet.c.subnet_class_name.is_null()
# → subnet_class_name=''
```

### ORDER BY

```python
Subnet.c.subnet_name.asc()     # subnet_name ASC
Subnet.c.subnet_name.desc()    # subnet_name DESC
```

---

## Combining conditions

`&` produces AND; `|` produces OR.  Both operators parenthesise both sides so
precedence is always explicit:

```python
(Subnet.c.site_id == "7") & (Subnet.c.subnet_name.like("%prod%"))
# → (site_id='7') and (subnet_name like '%prod%')

(Space.c.site_name == "prod") | (Space.c.site_name == "staging")
# → (site_name='prod') or (site_name='staging')
```

Required TAGS from both sides are unioned automatically:

```python
a = Subnet.c.env == "prod"     # required_tags: {'network.env'}
b = Subnet.c.tier == "web"     # required_tags: {'network.tier'}
c = a & b                      # required_tags: {'network.env', 'network.tier'}
```

### Iterables of conditions

`Session.list(where=...)` also accepts an *iterable* of `Condition` objects,
which are AND-ed together.  This is handy when building conditions dynamically:

```python
filters: list[Condition] = []
if site_id:
    filters.append(Subnet.c.site_id == site_id)
if name_prefix:
    filters.append(Subnet.c.subnet_name.like(f"{name_prefix}%"))

subnets = s.list(Subnet, where=filters)   # AND-ed; empty list → no WHERE clause
```

The free function `and_all(iterable)` does the same fold and can be called
explicitly; it raises `ValueError` on an empty iterable.

---

## TAGS — tagged class parameters

EfficientIP's TAGS mechanism exposes arbitrary class parameters as first-class
API columns.  Without TAGS, class params arrive as one concatenated blob
(`site_class_parameters = "key1=val1&key2=val2"`).  With TAGS, individual keys
become columns: `tag_site_key1 = "val1"`.

The expression builder handles TAGS transparently:

```python
# 'env' is not a declared field on Subnet
cond = Subnet.c.env == "prod"
str(cond)           # "tag_network_env='prod'"
cond.required_tags  # frozenset({'network.env'})
```

When you pass this `Condition` to `Session.list()`, the session:

1. Collects all `required_tags` from the `where` and `orderby` arguments.
2. Joins them with `&` into a `TAGS` query parameter (`network.env&network.tier`).
3. Appends any explicit `tags=` argument you supplied.
4. Builds the request with both `WHERE` and `TAGS` set correctly.

You never need to manage `TAGS` manually when using the expression builder.

### TAGS prefixes by model

| Model        | `tags_prefix` |
|--------------|---------------|
| `Space`      | `site`        |
| `Subnet`     | `network`     |
| `Pool`       | `pool`        |
| `IpAddress`  | `ip`          |
| `Vrf`        | `vrfobject`   |

---

## Inspecting expressions

Expressions expose human-readable representations:

```python
cond = (Subnet.c.site_id == "7") & Subnet.c.env.like("%prod%")

str(cond)
# "(site_id='7') and (tag_network_env like '%prod%')"

cond.required_tags
# frozenset({'network.env'})

repr(cond)
# "Condition(\"(site_id='7') and (tag_network_env like '%prod%')\")"
```

This makes debugging easy: print any `Condition` or `OrderByExpr` to see the
exact wire string that would be sent to the API.

---

## Complete examples

### Filter subnets by space and name pattern

```python
with Session(host, user, password) as s:
    subnets = s.list(
        Subnet,
        where=(Subnet.c.site_id == "7") & Subnet.c.subnet_name.like("prod-%"),
        orderby=Subnet.c.subnet_name.asc(),
        limit=50,
    )
```

### Filter by a tagged class parameter

```python
# Assume subnets have a class parameter 'environment' set via the EfficientIP UI.
# 'environment' is not a declared field, so it's auto-mapped to TAGS.
with Session(host, user, password) as s:
    prod_subnets = s.list(
        Subnet,
        where=Subnet.c.environment == "production",
        # Session auto-injects TAGS=network.environment
    )
```

### Filter by multiple tagged parameters with ORDER BY

```python
with Session(host, user, password) as s:
    results = s.list(
        Subnet,
        where=(
            (Subnet.c.environment == "production") &
            (Subnet.c.tier == "web")
        ),
        orderby=Subnet.c.priority.asc(),
        # Session injects TAGS=network.environment&network.priority&network.tier
    )
```

### Dynamic filter construction

```python
def find_addresses(
    s: Session,
    *,
    site_id: str | None = None,
    name_fragment: str | None = None,
    mac: str | None = None,
) -> list[IpAddress]:
    filters: list[Condition] = []
    if site_id:
        filters.append(IpAddress.c.site_id == site_id)
    if name_fragment:
        filters.append(IpAddress.c.name.like(f"%{name_fragment}%"))
    if mac:
        filters.append(IpAddress.c.mac_addr == mac)
    return s.list(IpAddress, where=filters)
```

### Use `id_filter` to relate objects

`SolidServerModel.id_filter` is a shortcut that returns a `Condition` matching
the object's own PK field — useful for fetching related objects:

```python
with Session(host, user, password) as s:
    space = s.get(Space, 7)
    # List all subnets belonging to this space:
    subnets = s.list(Subnet, where=space.id_filter)
    # → WHERE=site_id='7'

    # Combine with additional filters:
    subnets = s.list(
        Subnet,
        where=[space.id_filter, Subnet.c.subnet_name.like("%dmz%")],
    )
```
