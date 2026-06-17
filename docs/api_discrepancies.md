# SolidServer REST API v8.4 — Discrepancies between PDF documentation and observed behaviour

This file records places where the live API behaves differently from the PDF
reference (`SOLIDserver_API-Reference_REST-8.4.pdf`), and places where the
current SDK does not yet implement a documented option.  Entries marked
**[unconfirmed]** have not yet been verified against a live server.

---

## 1. `add_flag` defaults differ by model class in the SDK

**PDF**: all `*_add` services accept `add_flag` with values `new_edit` (default),
`new_only`, and `edit_only`.

**SDK behaviour**:

| Model | SDK `build_request("create")` | Effective `add_flag` |
|-------|-------------------------------|----------------------|
| `Space` | base implementation | `new_only` (explicit) |
| `Subnet` | override (does not call super for "create") | none sent → server default `new_edit` |
| `Pool` | override (does not call super for "create") | none sent → server default `new_edit` |
| `IpAddress` | override (does not call super for "create") | none sent → server default `new_edit` |

Consequence: creating an existing `Space` via `Session.flush()` raises
`ApiError` (server rejects the duplicate).  Creating an existing `Subnet`,
`Pool`, or `IpAddress` silently updates the object in place.

**Recommendation**: Document this difference in each model's docstring.  If
consistent behaviour is desired, either add `add_flag='new_edit'` to the base
`build_request` and let overrides opt out, or expose `add_flag` as a parameter
on `Session.flush()`.

---

## 2. `row_enabled` for Subnet — "Fixed value: 1 || 2" in PDF

**PDF** (`ip_subnet_add` parameters): `row_enabled` is described as
"Fixed value: 1 || 2" (i.e., only ENABLED or UNMANAGED are settable).

**SDK**: `RowEnabled.DELETED = 0` exists as a valid enum member and the SDK
serialises it via `_to_int_str`.

**[unconfirmed]**: Whether the server actually accepts `row_enabled=0` for a
subnet, or whether it rejects it / ignores it.  Live testing needed.

---

## 3. Pool creation — `site_id`/`site_name` in `create_fields` but rejected by `build_request`

**PDF** (`ip_pool_add`): `site_id` and `site_name` are listed as valid
alternatives to `subnet_id` for specifying the parent scope.

**SDK**: `Pool.create_fields` includes `site_id` and `site_name`, but
`Pool.build_request("create")` raises `ValueError` if `subnet_id is None`:

```python
if self.start_hostaddr is None or self.end_hostaddr is None or self.subnet_id is None:
    raise ValueError("start_hostaddr, end_hostaddr, and subnet_id are required …")
```

**Fix needed**: Either remove `site_id`/`site_name` from `Pool.create_fields`
(they cannot currently be used) or add a code path in `build_request` that
accepts them as alternatives.

---

## 4. Pool creation — `pool_size` as alternative to `end_addr`

**PDF**: `pool_size` is documented as a valid alternative to `end_addr` when
creating a pool.

**SDK**: `pool_size` is NOT in `Pool.create_fields` and is not handled in
`Pool.build_request("create")`.

---

## 5. Subnet creation — `permit_no_block`, `permit_invalid`, `permit_fragmented` flags

**PDF**: These flags are documented parameters of `ip_subnet_add`:
- `permit_no_block=1`: create a subnet without a parent block
- `permit_invalid=1`: allow overlapping networks
- `permit_fragmented=1`: allow fragmented allocation

**SDK**: None of these flags appear in `Subnet.create_fields` or
`Subnet.build_request`.  They cannot be passed via `Session.create()` (which
enforces `create_fields`).

**Workaround**: Construct the `Subnet` object manually, call `s.new(obj)`, and
manipulate `obj._dirty` directly before `s.flush()`.  Not ergonomic.

**Fix needed**: Add these flags to `create_fields` and handle them in
`write_params()` (they're boolean flags → `_to_bool_str`).

---

## 6. `ip_find_free_address` uses `rpc/` path, not `rest/`

**PDF**: `ip_find_free_address` is under `/rpc/`, not `/rest/`.

**SDK**: Not yet implemented.  When added, the path must be
`rpc/ip_find_free_address` (consistent with `ip_find_free_subnet` which already
uses `rpc/`).

---

## 7. `site_is_template` — immutable after creation

**PDF**: `site_is_template` is documented with "Can be edited: No".

**SDK**: `site_is_template` is in `Space.create_fields` (correct — it can be
set at creation) and is declared `frozen=True` on the `Space` model (correct —
prevents SDK-side mutation after construction).  The frozen guard mirrors the
API constraint.

**Note**: The server may silently ignore `site_is_template` on `ip_site_add`
PUT operations even though the SDK would not generate such a call.
**[unconfirmed]**

---

## 8. `subnet_addr` immutable after creation

**PDF**: `subnet_addr` is listed with "Can be edited: No" in `ip_subnet_add`.

**SDK**: `Subnet.subnet` (the `IPv4Network` field that encodes the address) is
`frozen=True`.  Any assignment raises `ValidationError`.  Correct behaviour.

---

## 9. Block-type subnet requires `subnet_level=0` in the request

**PDF**: To create a block-type network (as opposed to a subnet), `subnet_level=0`
must be explicitly included in the `ip_subnet_add` request.

**SDK**: `subnet_level` is in `Subnet.create_fields`.  However, the field
default is `None`.  If the caller omits `subnet_level`, it is not sent and the
server creates a non-block subnet.  There is no SDK-level guard that enforces
`subnet_level=0` for blocks.

**Recommendation**: Document clearly in `Subnet` and/or `Session.create()` that
`subnet_level=0` must be passed explicitly when creating a block.

---

## 10. MAC address format accepted by `ip_add`

**[unconfirmed]**: The PDF does not specify whether the server accepts colons
(`00:11:22:33:44:55`), dashes (`00-11-22-33-44-55`), or bare hex
(`001122334455`).  Live testing should verify which formats are stored and
which are echoed back by `ip_address_list`.

---

## 11. `errno` field present in all `*_list` rows, not only mutation responses

**PDF**: `errno` is documented only in the "Common output for `*_add` /
`*_delete`" section.

**Observed**: The live API includes `"errno": "0"` in every row of `*_list`
and `*_info` responses.

**SDK**: `errno` is declared on `SolidServerModel` and handled for all models.
Correct.

---

---

## 12. MAC address conflicts silently prevent updates

**Observed**: If a MAC address (e.g. `00:11:22:33:44:55`) is already registered to a
different IP record on the server, `ip_add` (POST or PUT) silently ignores the
`mac_addr` parameter and returns HTTP 200 with no error.  The existing MAC on the
record is left unchanged.

**SDK**: No validation or error is raised; `apply_response("update", data)` calls
`mark_clean()` unconditionally, so the caller has no way to detect that the MAC
was not updated.

**Workaround**: Use locally-administered MAC addresses (first octet second-LSB = 1,
e.g. the `52:54:00:*` range used by QEMU/KVM) for test data.  These are unlikely
to conflict with real registered hardware.

---

## 13. `mac_addr` is not updated by POST upsert (`new_edit`) for existing records

**Observed**: When `ip_add` is called with `new_edit` semantics (POST without
`add_flag`, or explicit `add_flag=new_edit`) and the IP record already exists,
the server updates name and class params but **silently ignores `mac_addr`**.
The MAC must be set explicitly via a subsequent PUT (`add_flag=edit_only`).

**PDF**: Does not document this distinction.

**SDK fix**: The `addr1` test fixture explicitly sets the MAC via a second
`flush()` (PUT) after the initial POST create/upsert.

---

## 14. `ip_add` returns HTTP 200 with empty body for non-terminal subnets

**Observed**: Calling `ip_add` against a subnet that does not have `is_terminal=True`
returns HTTP 200 with an empty response body.  The IP record is NOT created.  No
error code or message is returned.

**PDF**: Does not document this restriction.

**SDK**: After the client fix (`response.json() if response.content else []`),
`apply_response("create", [])` handles the empty response by clearing `_is_new`
without setting a PK, leaving `ip_id=None` as the indicator of a failed create.

---

*Last updated: based on PDF documentation review, static code analysis, and
live server testing.  Entries marked [unconfirmed] require further live testing.*
