# Hardware Identity Provider Implementation-Readiness Review

Status: Phase 1j readiness review complete; no provider, new identity algorithm,
request/license schema, signing payload, or migration code is implemented.

This document turns the Phase 1i compatibility audit into an implementation
boundary. It is a design decision for later, separately authorized work. The
source of truth for the current behavior remains `licensing/hwid.py`, and the
synthetic compatibility oracle remains `tools/check_hwid_contract_smoke.py`.

## Scope and non-goals

This review decides where a future provider belongs, what it may collect, what
must remain pure legacy-v1 behavior, how existing callers can receive injected
test seams, and how a future versioned identity could coexist with old requests
and licenses.

It does not:

- implement `HardwareIdentityProvider`;
- change `get_machine_id()` or any current source reader;
- add or select a new identity algorithm;
- change `LFREQ1`, `lfreq-1`, `lflic-1`, canonical JSON, or RSA verification;
- issue, migrate, or rewrite a license;
- claim native Linux or macOS identity support.

## Verified current call graph

The current client path is:

```text
ActivationWindow
  -> ActivationService.get_display_machine_id()
  -> ActivationService.generate_request_payload()
     -> licensing.hwid.get_machine_id()
     -> build_request_payload(machine_id)

LicenseManager.validate_license_data(license_data)
  -> schema and required-field validation
  -> verify_signature(...)
  -> licensing.hwid.get_machine_id()
  -> normalized exact machine_id comparison
```

`tools/license_admin.py` parses the request and delegates to
`tools/license_admin_core.py`. The administrator path copies the normalized
`machine_id` supplied by the request into the signed license payload. It does
not import or call `get_machine_id()` and must never acquire the customer's
device identity locally.

## Decision summary

| Topic | Decision |
| --- | --- |
| Provider location | A stdlib-only `shared/platform/identity.py` boundary, wired by `licensing/hwid.py` |
| Provider responsibility | Acquire the exact legacy input values and metadata only |
| Legacy transform | Pure functions outside the provider own fallback construction, serialization, UTF-8, and SHA-256 |
| Public facade | Keep `get_machine_id() -> str` and `get_machine_fingerprint_parts() -> Dict[str, str]` unchanged |
| Test seam | Inject an immutable provider instance or factory into an internal calculation helper; never use a mutable global singleton |
| Application service seam | Prefer an optional keyword-only machine-ID callable |
| License validation seam | Prefer an optional keyword-only machine-ID callable, invoked only after successful signature verification |
| Migration | Decision: Option B — old containers remain legacy-v1; a new schema explicitly selects v2 |
| Multi-ID fallback | Unversioned multi-ID fallback: Rejected |
| Next implementation | Phase 1k extracts only behavior-equivalent legacy-v1 collection and pure transforms |

## Provider responsibility decision

The provider belongs at `shared/platform/identity.py`, alongside the existing
platform boundaries. The module must remain stdlib-only and must not import Qt,
editor code, licensing schemas, request encoders, signing code, AppData paths,
or runtime orchestration.

To avoid a `shared -> runtime` dependency, the Windows provider should accept a
narrow command-execution callable during construction. `licensing/hwid.py` may
wire the current `runtime.command_runner.execute_command` callable into the
provider factory. Construction must be side-effect free; the provider calls the
injected command runner only from `collect_parts()`.

The provider owns only acquisition and call order:

1. the registry-derived `machine_guid` value;
2. the complete command `stdout` used as `volume_serial`;
3. the five fallback source values in their current order;
4. the currently observable Python-version and `platform.platform()` metadata.

The provider must not own request encoding, license signing or verification,
UI display formatting, logging, AppData storage, schema selection, migration,
or compatibility fallback across identity versions.

### Frozen HardwareIdentityParts

Phase 1k should introduce an immutable, frozen `HardwareIdentityParts` value
object with these exact string fields and order:

```text
machine_guid
volume_serial
fallback
python
platform
```

The order and values match the Phase 1i observable dictionary. A conversion at
the existing facade boundary must return a normal insertion-ordered dictionary
with those exact keys. The value object is internal and must never be serialized
into a user plan, request, license, diagnostic report, or log.

The provider invokes the source readers. A pure fallback builder, not the
platform source reader itself, owns the current truthiness filtering, `str()`
conversion, and literal `|` joining. This keeps source acquisition replaceable
without making normalization provider-specific.

## Legacy-v1 pure-function boundary

Phase 1k should extract and freeze three independently testable pure operations:

1. `build_legacy_v1_fallback(system, release, version, hostname, username)`
   filters falsy values, applies `str()`, preserves case and whitespace, and
   joins the remaining values with literal `|` in the current order.
2. `serialize_legacy_v1(parts)` reads only `machine_guid`, `volume_serial`, and
   `fallback`, substitutes an empty string for a missing value, and joins the
   three values with literal `||`.
3. `hash_legacy_v1(parts)` encodes that serialization as UTF-8, calculates
   SHA-256, and returns exactly 64 uppercase hexadecimal characters.

The `python` and `platform` metadata fields remain observable through
`get_machine_fingerprint_parts()` but must not enter the legacy-v1 hash. No
trimming, case conversion, Unicode normalization, path normalization, locale
parsing, return-code interpretation, or source-priority rule may be added to
these pure functions.

Registry and volume exceptions must still become empty strings. Volume
`returncode` and `stderr` must remain ignored, and non-empty `stdout` must still
be used even when the return code is nonzero. Fallback-source exceptions must
still propagate. These unusual rules are compatibility requirements, not a
recommendation for a future v2 algorithm.

## Public facade strategy

The public functions remain in `licensing/hwid.py` with their current signatures:

```python
get_machine_fingerprint_parts() -> Dict[str, str]
get_machine_id() -> str
format_machine_id(machine_id: str, group: int = 4) -> str
```

`get_machine_id()` continues to mean legacy-v1 until an explicitly versioned
API is introduced. Existing callers therefore do not change in Phase 1k.

For testability, a private calculation helper may accept a
`HardwareIdentityProvider`, and a side-effect-free factory may create the
default provider per public call. The production default must preserve the
current `os.name` selection semantics. The implementation must not use a
mutable process-global provider, read identity at import time, or cache an ID
derived while a source is temporarily unavailable. Repeated calls may collect
again, matching current behavior.

## ActivationService injection strategy

Current behavior: `ActivationService` imports `get_machine_id()` directly.
`get_machine_id()` is called by its raw-ID method; the display method calls the
imported facade directly; request payload generation calls the service method.

The four options were reviewed:

1. **Constructor-injected callable:** smallest API and test seam; no provider
   knowledge leaks into the application service.
2. **Constructor-injected provider:** exposes low-level parts collection and
   forces the service to know the hashing/version boundary.
3. **Injected HardwareIdentityService:** supports richer future state but is an
   unnecessary abstraction before error/status requirements are implemented.
4. **Keep only the imported facade:** maximizes present compatibility but leaves
   tests dependent on module monkeypatching and makes lifecycle policy implicit.

Decision: add an optional keyword-only `Callable[[], str]` only in a separately
authorized implementation slice, defaulting to the existing facade. Store the
callable without invoking it in `__init__`; route both raw and display methods
through the same stored callable. Existing positional construction remains
valid, and the UI needs no new provider awareness. If `ActivationService`
constructs a `LicenseManager`, it should pass the same callable so one service
instance cannot calculate requests and validate licenses through different
identity seams.

Phase 1j changes none of those signatures.

## LicenseManager injection strategy

Current behavior validates the schema and required fields, verifies the
signature, returns `invalid_signature` on failure, and only then calls
`get_machine_id()` for the normalized exact comparison. That order is a privacy
and security contract.

Decision: a future, separately reviewed change may add an optional keyword-only
`Callable[[], str]` defaulting to `get_machine_id`. The constructor stores it
without invocation. `validate_license_data()` calls it only after the signature
has succeeded and only for the identity version selected by the already
validated, signed container.

The manager must never:

- collect identity before signature verification;
- translate a provider exception into `invalid_signature`;
- try every locally available candidate and accept the first match;
- treat an unsigned or absent version hint as permission to weaken matching;
- route an old license to anything except exact legacy-v1 verification.

For a future versioned schema, the manager may receive an immutable mapping of
version names to zero-argument resolvers. It must select exactly one resolver
from the signed version field after schema and signature checks. There is no
ambient fallback chain.

## Admin-tool boundary

The administrator tools remain identity-source agnostic. They accept a parsed
request, normalize its supplied `machine_id`, and copy it into the license
payload that is subsequently signed. A future provider must not be imported,
constructed, or invoked by `tools/license_admin.py`,
`tools/license_admin_core.py`, or `tools/license_generator.py`.

Future versioned admin support may validate and copy a signed-container-bound
identity version and value. It must not recompute the customer's identity,
guess a version, or silently convert between versions.

## Versioning options reviewed

### Option A — legacy-v1 forever, provider abstraction only

- Existing-license compatibility and rollback are simple because all clients
  and signatures retain the current field.
- There is no downgrade ambiguity and no request-size or UI growth.
- It cannot provide a stable native identity for new platforms or correct known
  locale, hostname, account, and installation sensitivity.
- Support and privacy costs stay permanently coupled to the current inputs.

This is safe for Phase 1k extraction but not the long-term migration strategy.

### Option B — old containers use legacy-v1; a new schema selects v2

- `LFREQ1`, legacy request payloads, `lfreq-1`, `lflic-1`, and unversioned legacy
  licenses remain byte-for-byte and semantically compatible.
- A new request prefix/schema and license schema carry an explicit identity
  version. The license's signed payload covers the version and value together.
- A valid container selects exactly one algorithm, preventing an unsigned
  downgrade or “match any local ID” bypass.
- Request size, UI labels, admin parsing, support playbooks, reactivation, and
  rollback become more complex, but the complexity is explicit and testable.
- Privacy review can be specific to the v2 input set instead of inheriting it
  accidentally through an unversioned field.

This is the recommended migration strategy.

### Option C — every request carries both legacy-v1 and v2

- It eases side-by-side issuance and rollback for a limited transition.
- It increases request size, persistent-identifier exposure, UI ambiguity,
  admin-tool complexity, and support burden.
- Unless the container and selection policy are signed/versioned, it introduces
  downgrade and substitution opportunities. Old tools may misparse new fields.

This is rejected as the default. A future, explicitly versioned transition
container could carry more than one labeled value only after a separate privacy
and threat-model approval; it cannot authorize match-any verification.

### Option D — compute candidate IDs locally; bind a license to one versioned ID

- A signed version/value pair can be secure when the client dispatches only to
  the named algorithm.
- Computing all candidates on every validation expands data acquisition,
  permissions, side effects, spoofing surface, and privacy cost.
- Trying candidates until one matches makes rollback opaque and can silently
  weaken device binding.

This is rejected as a standalone match-any strategy. Option B may use a strict
version-to-resolver dispatch table, but only the single version named by the
validated signed license may run.

## Recommended versioning strategy

Decision: Option B.

Existing containers remain unchanged. A future proposal should use a distinct
request prefix and schema such as `LFREQ2` / `lfreq-2`, and a distinct license
schema such as `lflic-2`. The exact names and fields require their own Phase 1l
review, but the contract must include an explicit identity algorithm version
and identity value. Both are covered by the canonical signed license payload.

An old administrator tool must fail closed on the new prefix rather than parse
it as `LFREQ1` or silently treat it as an old unversioned request. A new admin
tool must continue to parse and issue legacy containers through an explicit
legacy mode while that client line remains supported.

The new client selects exactly one resolver from the signed license version.
It does not calculate a set and accept any match. Rollback means installing a
client/configuration that still implements the same signed schema; it never
means deleting the version field or interpreting v2 as legacy-v1.

## Rejected strategies

Unversioned multi-ID fallback: Rejected.

Also rejected:

- replacing the legacy-v1 algorithm in place behind `get_machine_id()`;
- adding unsigned version metadata beside `lflic-1`;
- adding fields to `lflic-1` and assuming old signatures remain compatible;
- accepting legacy-v1 or v2 when either one happens to match;
- inferring the identity version from ID length or formatting;
- recomputing customer identity inside the administrator tool;
- caching a degraded identity as a permanent device ID.

## Legacy-license interpretation

The permanent interpretation rules are:

1. `LFREQ1` and currently supported legacy request payloads always carry a
   legacy-v1 machine ID.
2. `lflic-1` and the older unversioned license shape always bind legacy-v1.
3. Absence of an identity-version field means legacy-v1 only; it never means
   “current default algorithm.”
4. The legacy-v1 acquisition, fallback, serialization, and hash implementation
   must remain available to future clients that validate these licenses.
5. A future v2 client validating `lflic-1` explicitly selects legacy-v1.
6. A v2 license does not fall back to legacy-v1 by default.
7. Any future transitional fallback must be explicitly represented and covered
   by the signed payload, constrained to named versions, and separately threat
   modeled. The current recommendation is no fallback.
8. Legacy issuance capability must remain available for supported old clients,
   as an explicit admin operation rather than silent auto-selection.

Legacy-v1 is permanent verification behavior for LFREQ1, legacy request
payloads, lflic-1, and unversioned legacy licenses. It cannot be replaced in
place even after a new default identity exists.

## Migration and reactivation policy

No existing license is rewritten. Users with a valid legacy license continue
to validate through legacy-v1. A client upgrade alone does not migrate a
license, and a v2 request does not invalidate the old signed artifact.

When a user elects or is required to move to a v2 license:

1. the new client creates an explicitly versioned request;
2. the admin tool displays masked identity/version metadata and requires an
   explicit issuance choice;
3. a new signed license is issued with a new audit record;
4. the old license remains independently verifiable according to its lifecycle
   and support policy;
5. rollback restores a client capable of that license schema, not a weakened
   cross-version matcher.

If the legacy-v1 value cannot be reproduced after reinstall, permission,
language, hostname, account, disk, VM, clone, or hardware change, support must
use a human-approved reactivation/reissue flow. The new request becomes the
evidence for a new signed license. Support must not reconstruct raw identity
parts from logs, edit a signed payload, or accept a partially matching ID.

Recovery policy still needs product decisions for entitlement limits,
revocation, duplicate requests, offline proof of ownership, rate limits, and
old-license retirement. Those decisions are prerequisites for Phase 1l, not
authorization to modify the current client.

## Error-state model

No production error code changes in Phase 1j or the behavior-equivalent portion
of Phase 1k. A future result model should distinguish:

| State | Meaning | Required handling |
| --- | --- | --- |
| `schema unsupported` | Container version is not implemented | Fail before identity acquisition and report the unsupported schema |
| `signature invalid` | Signed payload authenticity failed | Fail before identity acquisition; never call a provider |
| `identity unavailable` | The selected provider cannot safely produce its identity | Report identity acquisition separately; do not cache or mislabel as signature failure |
| `identity degraded` | An ID was produced with one or more unavailable/failed sources | Preserve exact legacy output where required, retain only non-sensitive status metadata, and do not make it a permanent cached identity |
| `identity produced` | The selected algorithm completed under its defined source policy | Compare only against the signed value for that version |
| `legacy mismatch` | A valid legacy license's normalized ID differs from calculated legacy-v1 | Report device mismatch only after successful signature verification |

Current legacy-v1 behavior remains exact during extraction:

- MachineGuid failure becomes an empty value.
- Volume launch failure becomes an empty value.
- Empty volume stdout remains empty.
- A nonzero volume return code remains ignored and stripped stdout is used.
- Fallback-source exceptions propagate.
- A hostname or username change can change the result.
- Localized full volume stdout can change when the system language changes.
- Partial fields still produce a legacy SHA-256 value.

A future status object may record source availability and failure categories,
but it must not include raw parts in exceptions or logs and must not alter the
legacy-v1 bytes. Provider exceptions are identity failures, never signature
failures. No degraded or empty-source result may be cached as a permanent ID.

## Privacy and logging requirements

A stable hash remains a persistent device identifier; hashing does not make it
anonymous. Future provider work must enforce all of the following:

- raw MachineGuid never enters logs;
- raw volume stdout never enters logs;
- hostname and username never enter ordinary logs;
- `HardwareIdentityParts` never enters diagnostics;
- a complete machine ID never enters ordinary logs;
- a complete request token never enters ordinary logs;
- a license body or signature never enters ordinary logs;
- user-visible or support output uses only a documented masked ID with a small
  prefix and suffix;
- exceptions contain source/status labels only, never raw parts;
- synthetic fixtures remain obviously fictional and isolated from host APIs;
- no identity source is read at import time or merely to render an unrelated UI;
- identity collection occurs only after schema/signature gates where validation
  ordering requires it.

Current future-redaction review points are the activation window's display/copy
surfaces, request-copy feedback, license-manager error presentation, admin
inspection/history output, and diagnostic masking. Phase 1j changes none of
these. Any future UI/support design must preserve deliberate copy actions while
keeping ordinary logs and diagnostics masked.

## Implementation slices

### Phase 1k — behavior-equivalent legacy-v1 extraction

Keep this phase narrowly split into reviewable commits:

1. Add the frozen parts type, provider protocol, side-effect-free factory, and
   exact Windows/legacy collection implementations.
2. Extract the pure legacy-v1 fallback/serialization/hash functions and route
   the unchanged `licensing/hwid.py` facade through them.
3. Only after equivalence is proven, consider the optional callable seams for
   `ActivationService` and `LicenseManager` in a separate small change.

Acceptance requires character-for-character production output, unchanged
public facades, all Phase 1i fixtures, source-order/error fixtures, import
side-effect checks, no schema/request/license/RSA change, and no new algorithm.
The provider must not be implemented as a global mutable singleton.

### Phase 1l — versioned request/license container

Design and implement a new request prefix/schema and license schema. Preserve
all old parsers and validation paths. Cover the identity version and value with
the license signature; make old tools reject the new prefix cleanly; retain an
explicit legacy issuance path; add downgrade, tampering, unsupported-schema,
rollback, and reissue tests. This phase does not change legacy-v1 interpretation.

### Phase 1m — new identity algorithm experiment

Prototype v2 outside the production default path. Gather real-host evidence for
Windows reinstall, permissions, locale, hostname/account changes, disk changes,
VM/container/clone behavior, and upgrades. Separately validate native Linux and
macOS sources on real supported architectures. Complete collision, spoofing,
privacy, recovery, and support analysis before any production selection.

These phases must not be merged into one large change.

## Evidence still required before production changes

Phase 1k authorization still needs:

- an approved exact module/API diff for the provider and pure functions;
- a dependency-direction review for the injected command runner;
- synthetic tests proving every Phase 1i source order and error case against
  both old and proposed implementations;
- proof that source and frozen imports perform no identity acquisition;
- an explicit decision on whether callable injection ships in the same phase or
  a second small Phase 1k change;
- packaging/import validation after implementation, without changing releases.

Phase 1l additionally needs an approved canonical schema, prefix, signed-field
set, admin compatibility matrix, downgrade threat model, reactivation policy,
and rollback/support lifecycle. Phase 1m needs the real-host evidence listed
above. Until those gates pass, the current algorithm and schemas remain the only
production behavior.

## Readiness conclusion

The implementation boundary is ready for a separately authorized Phase 1k:
extract acquisition behind a stdlib-only provider, retain legacy transforms as
pure functions, and keep the public facade and all signed containers unchanged.
HardwareIdentityProvider is not implemented in Phase 1j. HWID v2, schema
migration, native platform identity, and license migration also remain
unimplemented.
