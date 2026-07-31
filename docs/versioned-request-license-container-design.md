# Versioned Request and License Container Design Freeze

Status: Phase 1l design freeze complete; implementation not started.

This document is the security and compatibility contract for a future
versioned request and license container. It does not change a production
parser, encoder, schema, signature, key, identity algorithm, administrator
tool, or client. `LFREQ1`, `lfreq-1`, `lflic-1`, and every unversioned legacy
license remain production behavior and remain permanently bound to
`legacy-v1`.

Unchanged-production evidence is an external pre/post SHA-256 gate, not a key
resource read by the design smoke. Completion requires
`protected_files_checked > 0`, `changed=0`, and `hash_mismatch=0`.

The only recommended future containers are:

```text
LFREQ2.<payload_b64url>.<checksum_hex>
LFLIC2.<payload_b64url>.<signature_b64url>
```

They are design names, not implemented formats. HWID v2 is not defined or
implemented by this design.

## 1. Scope and security boundary

Phase 1l freezes:

- the real current request and license wire contracts;
- three independent version concepts;
- one request framing and one license framing;
- exact canonical JSON and signing bytes;
- strict parser, field, size, downgrade, migration, reissue, and rollback
  policy;
- non-production synthetic design vectors.

It does not implement a parser, encoder, signer, identity resolver, migration,
reissue UI, or release artifact. A stable machine ID remains a persistent,
linkable device identifier; hashing it does not make it anonymous. Neither the
new request nor any ordinary log may contain raw MachineGuid, raw volume
output, hostname, username, `HardwareIdentityParts`, or a candidate-ID list.

## 2. Three independent versions

| Concept | Exact field or framing | Meaning | Never inferred from |
|---|---|---|---|
| Container Version | case-sensitive outer prefix plus signed/checked `container_version` | segment framing, alphabet, padding, and domain binding | prefix case, field presence, or payload appearance |
| Payload Schema Version | signed/checked `schema` | exact JSON fields, types, constraints, and semantics | machine-ID length or container version alone |
| Identity Algorithm Version | `identity_algorithm` plus `identity_value`; checksum-covered in `LFREQ2`, signed in `LFLIC2` | the one authoritative resolver and its canonical value | hash length, casing, or local default |

Recommended exact fields are `container_type`, `container_version`, `schema`,
`identity_algorithm`, and `identity_value`. A generic field named only
`version` is forbidden because it would conflate the three meanings.

## 3. Frozen current request contract

The real implementation is `licensing/request_token.py`; there is no
`licensing/request_code.py` in the current repository.

### 3.1 `LFREQ1` / `lfreq-1` wire

| Property | Frozen current behavior |
|---|---|
| Outer prefix | exact, case-sensitive `LFREQ1` |
| Segments | exactly three: prefix, payload, checksum |
| Separator | literal `.` |
| Payload encoding | `urlsafe_b64encode(raw).decode("ascii").rstrip("=")` |
| Decode padding | decoder appends enough `=` to reach a multiple of four; it does not enforce a canonical no-padding input |
| Decode strictness | no explicit alphabet validation and no decode/re-encode equality check |
| Checksum | lowercase SHA-256 hex of decoded raw payload bytes, truncated to 12 characters (48 bits) |
| Checksum comparison | received checksum is lowercased, so uppercase hex is accepted |
| Checksum coverage | decoded raw JSON bytes only; prefix and Base64URL spelling are not covered |
| Canonical emitter | `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")` |
| Payload schema | exact `lfreq-1` |
| Factory fields | `schema`, `product`, `app_version`, `machine_id`, `request_id`, `created_at` |
| Factory order | insertion order is as listed, but wire key order is lexicographic and semantic field order is not significant |
| Request signature | none |
| Maximum size | none |

The checksum detects likely copy damage only. It is not a MAC, signature,
source authentication mechanism, entitlement proof, or anti-replay control.

### 3.2 Current request field and parse behavior

The factory emits strings: fixed `schema` and `product`, current
`app_version`, uppercase/trimmed `machine_id`, a UUID string, and a seconds
precision UTC ISO timestamp ending in `Z`. The parser is intentionally looser
than those emitted types:

- required values are checked through `str(value).strip()`, not strict type
  checks;
- `schema` must equal `lfreq-1` exactly;
- `product` is compared case-insensitively through `str(value).lower()` and is
  normalized to `launchflow`; it is not trimmed, so surrounding whitespace
  fails the comparison;
- `machine_id` is converted with `str`, trimmed, and uppercased, with no length,
  alphabet, or Unicode-normalization rule;
- `request_id` only has to be accepted by `UUID(str(value))`; canonical text
  and UUID version are not enforced, and the original value/spelling is kept;
- `created_at` only has to be accepted by `datetime.fromisoformat` after a `Z`
  replacement; UTC and the emitter's exact spelling are not enforced, and the
  original value/spelling is kept;
- the generic required check treats `str(None)` as non-empty: for example,
  `app_version: null` can remain JSON `null`, while `machine_id: null` becomes
  the literal string `NONE`; null schema/product/request/time still fail their
  later specific validation;
- unknown top-level fields are preserved; in a received token they are already
  covered by that token's raw-payload checksum, and only a later explicit
  re-encode would include them in a newly canonicalized checksum;
- duplicate JSON keys are not rejected; standard-library JSON last-key-wins
  behavior applies;
- decoded JSON need not itself be canonical if its checksum matches;
- JSON strings use UTF-8 and `ensure_ascii=False`, but no NFC normalization or
  control-character policy exists;
- missing or string-empty required values fail, while many non-string truthy
  values can pass the loose conversion boundary.

The parser trims outer whitespace, then rejects any remaining whitespace. A
matching `LFREQ1` prefix with wrong segment count, checksum, UTF-8, JSON,
schema, product, UUID, or timestamp raises `RequestTokenError` with a
malformed/damaged/unsupported message. Any text not starting with exact
`LFREQ1.` is routed to the broad legacy Base64URL-JSON fallback rather than an
explicit unknown-prefix branch.

The legacy request fallback is one permissively decoded Base64/URL-safe JSON
object with no prefix, checksum, required/recognized schema, or signature. An
input `schema` field may exist but is ignored. The fallback requires only a
non-empty `machine_id` and returns exactly `schema="legacy"`, `product`,
`app_version`, uppercase `machine_id`, `request_id`, `created_at`, and
`legacy=True`. `created_at` prefers input `generated_at`, then `created_at`,
then `legacy-unknown`. The transitional ID is `legacy-` plus the first 32 hex
characters of SHA-256 over the outer-trimmed original token's UTF-8 text. It
permanently means `legacy-v1`.

## 4. Frozen current license contract

### 4.1 `lflic-1` wire and schema

`lflic-1` is not an external container prefix. A current `.lic` (or accepted
`.json`) is a UTF-8 JSON object. It has no outer prefix, payload segment, or
separate signature segment. Pretty-print whitespace, object insertion order,
file name, and extension do not participate in the signature.

The current required key-presence set is exactly:

```text
schema
license_id
request_id
product
machine_id
customer
edition
features
issued_at
expires_at
request_app_version
min_app_version
max_app_version
signature
```

`max_app_version` must be present but may be JSON `null`. The admin emitter
uses strings for identifiers/text/time/version values, `list[str]` for
`features`, and normalized uppercase `machine_id`. Client validation is
looser: `license_id`, `request_id`, `edition`, and `request_app_version` need
only key presence; `machine_id`, `customer`, and `min_app_version` must be
non-empty after `str(...).strip()`; `features` need only be a list and its
elements are not type-checked; `max_app_version` is null or a parseable version
not below minimum; issued/expires values are converted through `str` and ISO
parsed. Product comparison is case-insensitive but is not trimmed and does not
normalize the payload object.

Unknown top-level fields are accepted. Every field other than the exact
`signature` key, including unknown fields, enters the signing payload.
Duplicate keys are not rejected by `read_json`; last-key-wins behavior applies.
There is no file, object, field, or nesting size limit and no requirement that
the on-disk JSON bytes be canonical.

### 4.2 Frozen signing bytes and algorithm

Current signing bytes are exactly:

```python
json.dumps(
    payload_without_signature,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

The signature algorithm is RSA PKCS#1 v1.5 with SHA-256. The emitter preserves
standard Base64 `=` padding; this is not Base64URL. The client first trims
outer whitespace from the signature string, then uses standard Base64 decode
with `validate=True`, so internal whitespace and non-alphabet characters fail.
There is no signed or outer signing-algorithm identifier and no key identifier.
The signature covers schema, product, identity value, edition, features,
validity, license/request identifiers, version bounds, and every accepted
unknown field. It does not cover its own `signature` value.

### 4.3 Frozen client validation order

Current `LicenseManager` performs:

1. read `schema`; only a missing key, JSON `null`, or exact empty string selects
   legacy, exact `lflic-1` selects current, and every other value—including
   `0`, `false`, or an empty array—returns unsupported schema;
2. for `lflic-1`, validate shape/product/features/time/version fields; for a
   missing, `null`, or empty schema, select the unversioned legacy shape;
3. require the legacy key-presence set when applicable;
4. build all-fields-except-signature payload and verify the signature;
5. only after a valid signature, call `get_machine_id()` once;
6. compare `current_machine_id.upper()` with the trimmed/uppercased signed
   `machine_id` exactly;
7. evaluate app-version compatibility and expiration for `lflic-1`, or the
   legacy local-time expiry for an unversioned license.

A bad signature does not acquire identity. Machine mismatch does not try a
second algorithm. Current ISO time parsing accepts more spellings than the
admin emits: naive values are treated as UTC and offset values are converted
to UTC. It does not enforce `issued_at < expires_at`; expiry uses strict
`now > expires_at`. If version is both incompatible and expired,
`app_version_not_allowed` returns first. Malformed file JSON is reported by the
load boundary as `license_read_failed`; a syntactically valid non-object is not
consistently converted to a structured schema error.

### 4.4 Unversioned legacy license fallback

A missing, JSON `null`, or exact empty-string `schema` permanently selects the older license
shape with `license_id`, `tester_name`, `machine_id`, `edition`, `expire_at`,
`created_at`, and `signature`. Its signature uses the same canonical JSON and
RSA algorithm over all fields except `signature`. Expiry is parsed as local
naive `YYYY-MM-DD HH:MM:SS`; `created_at` is not parsed. Required fields are
checked for presence only. Extra fields—including product, request correlation,
features, version-range metadata, or a present `schema: null`/`schema: ""`
key—are accepted and enter the all-fields-except-signature payload, but the
legacy validator defines no authorization semantics for them. The format
always means `legacy-v1`.

## 5. Recommended request container

### 5.1 Framing

The one recommended request grammar is:

```text
LFREQ2.<P>.<C>
```

- prefix: exact, uppercase, case-sensitive ASCII `LFREQ2`;
- segments: exactly three, separated by literal `.`;
- `P`: unpadded strict Base64URL of the canonical payload bytes;
- `C`: exactly 64 lowercase hexadecimal characters equal to
  `SHA256(b"LFREQ2." + P.encode("ascii")).hexdigest()`;
- any leading, trailing, or internal whitespace is rejected rather than
  stripped;
- the checksum binds the spelling of the prefix and payload segment but remains
  unauthenticated and forgeable.

### 5.2 Exact request payload

All fields are required; unknown fields are rejected.

| Field | Type | Exact rule |
|---|---|---|
| `container_type` | string | exact `request` |
| `container_version` | integer | exact `2`; Boolean is not an integer |
| `schema` | string | exact `lfreq-2` |
| `product` | string | exact lowercase ASCII `launchflow` |
| `app_version` | string | canonical SemVer 2.0.0 text, 1..64 ASCII bytes |
| `request_id` | string | canonical lowercase RFC 4122 UUIDv4, exactly 36 ASCII characters |
| `created_at` | integer | UTC Unix epoch seconds, `0..253402300799` |
| `identity_algorithm` | string | case-sensitive registered token matching `[a-z][a-z0-9._-]{0,31}` |
| `identity_value` | string | algorithm-specific canonical ASCII, 1..512 bytes globally |

The only currently implemented identity algorithm remains `legacy-v1`; its
canonical value is exactly 64 uppercase hexadecimal characters. A future
algorithm identifier and its input/hash contract require Phase 1m review and
are deliberately not named here. Carrying `legacy-v1` in `LFREQ2` is an
explicit field value, never an inferred fallback, and must not become a silent
issuance default.

`request_id` is correlation only: it is a client-chosen uniqueness value, not
an authentication token, proof of freshness, or replay-prevention nonce. The
`created_at` timestamp is untrusted requestor-supplied context, not trusted
server time. A timestamp more than five minutes in the future is rejected; one
older than 30 days needs an explicit, audited operator override, but neither
decision makes the request authentic. A forged request can use a fresh UUID,
timestamp, identity, and recomputed checksum, so human entitlement/ownership
review remains mandatory.

### 5.3 Request trust boundary

`LFREQ2` is unauthenticated. Its checksum is forgeable and detects only
accidental transport or copy damage. Until an administrator completes external
authorization review, every payload field is untrusted input:

- `request_id` is a correlation identifier only, and `created_at` is an
  untrusted claimed time. A UUID and timestamp do not prevent replay.
- `product` and `app_version` provide review context only; they never grant
  eligibility to receive a license.
- `identity_algorithm` states the requestor's desired binding algorithm. The
  administrator accepts it only under the explicitly selected issuance mode
  and an administrator-side algorithm allowlist.
- `identity_value` is chosen by the requestor. It is only the proposed target
  identifier to bind and does not prove that the request came from that device.
- Request fields do not grant entitlement. The request schema therefore
  forbids `customer`, `edition`, `entitlements`, validity fields,
  `signing_algorithm`, `key_id`, signing-key overrides, and administrator-policy
  overrides.
- Customer, edition, entitlements, validity, and product policy come from
  administrator authorization records or explicit administrator input, never
  by automatic inheritance from a request.

Request replay requires administrator-side persistent state. A later admin
implementation must atomically check and record at least `(schema, request_id)`
against the applicable order/authorization record before issuance. A repeated
processed ID fails closed; a reused ID with different canonical payload bytes
is an audited conflict, not a reissue. If required replay/authorization state
is unavailable, inspection may continue but issuance fails closed. A checksum,
UUID, timestamp, first-seen status, or operator age override alone is not replay
protection or ownership proof. This persistent request-ID registry is an
implementation requirement; it is not implemented by Phase 1l.

### 5.4 Request UI and admin policy

The client may visually wrap the token but copies one exact line. It separately
shows `LFREQ2 / lfreq-2`, masked identity, identity algorithm, client version,
and UTC request time, plus an explicit warning that the checksum is not
authentication. Ordinary logs and diagnostics never contain the full token or
identity value.

The admin parses framing and canonical payload strictly, displays only masked
identity metadata, and copies the supplied canonical identity value into an
approved license. It never recalculates a customer's identity. The admin
defaults to inspect-only, and inspecting a request never issues a license. The
issuance mode is explicit: `legacy-lflic-1` or `versioned-lflic-2`. The request
prefix does not select issuance mode; receiving `LFREQ2` never automatically
issues `LFLIC2`, and receiving a legacy request never silently downgrades.

## 6. Recommended license container

### 6.1 Framing and signature segment

The one recommended license grammar is:

```text
LFLIC2.<P>.<S>
```

- prefix: exact, uppercase, case-sensitive ASCII `LFLIC2`;
- segments: exactly three, separated by literal `.`;
- `P`: unpadded strict Base64URL of the canonical unsigned payload;
- `S`: unpadded strict Base64URL of the RSA signature;
- file name and extension have no security meaning;
- no unsigned sidecar/header/query metadata may select schema, key, algorithm,
  identity resolver, product, or entitlement.

### 6.2 Exact license payload

All listed fields are required. `max_app_version` is the only nullable field.
Unknown fields are rejected.

| Field | Type | Exact rule |
|---|---|---|
| `container_type` | string | exact `license` |
| `container_version` | integer | exact `2`; Boolean rejected |
| `schema` | string | exact `lflic-2` |
| `signing_algorithm` | string | exact `rsa-pkcs1v15-sha256`; fixed allowlist declaration, not negotiation |
| `key_id` | string | exact `spki-sha256:` plus 64 lowercase hex characters |
| `license_id` | string | canonical lowercase UUIDv4 |
| `request_id` | string | canonical lowercase UUIDv4 copied from the approved request |
| `product` | string | exact `launchflow` |
| `identity_algorithm` | string | the one signed, registered resolver token |
| `identity_value` | string | the one signed algorithm-specific canonical value |
| `customer` | string | already NFC; 1..128 Unicode code points and at most 256 UTF-8 bytes |
| `edition` | string | lowercase ASCII token `[a-z0-9][a-z0-9._-]{0,31}` |
| `entitlements` | array of strings | 0..64 sorted, unique lowercase ASCII tokens; each 1..64 characters |
| `issued_at` | integer | UTC Unix epoch seconds in the defined range |
| `expires_at` | integer | UTC Unix epoch seconds; strictly greater than `issued_at` |
| `min_app_version` | string | canonical SemVer 2.0.0, 1..64 ASCII bytes |
| `max_app_version` | string or null | canonical SemVer not below minimum, or JSON `null` |

`signing_algorithm` and `key_id` are fields inside the signed payload. The
verifier accepts only an exact, case-sensitive `(signing_algorithm, key_id)`
pair present in a bounded trusted key registry compiled into the client or
packaged as immutable configuration authenticated by the same client-release
trust chain. The registry cannot come from user-writable configuration or
runtime injection. It maps that pair to one pinned public verification key and
its trusted RSA modulus length. The payload pair is an untrusted selector until
signature verification; it never dynamically selects an arbitrary
cryptographic primitive.

`key_id` is exactly `spki-sha256:` plus the full lowercase SHA-256 digest of the
key's DER SubjectPublicKeyInfo. `key_id` is never treated as a file path, URL,
environment variable, Windows Registry location, AppData/config lookup, or
network reference. The verifier never guesses a key from signature length,
modulus appearance, payload shape, or partial/case-folded key ID. It performs
one exact trusted-registry lookup first, checks the decoded signature length
against that entry's modulus length, and then verifies the signature.

An unknown signing algorithm or key ID fails closed before identity collection.
There is no default key, try-every-key behavior, legacy-algorithm fallback, or
retry with a different pair. Key rotation adds a new explicitly trusted
registry entry and key ID; it does not relax lookup. This supports bounded key
selection but does not solve offline key revocation.

The request correlation is mandatory. Reissue/supersession relationships stay
in immutable admin audit history rather than a license field, because a local
offline client cannot enforce revocation merely from such a claim.

The syntax of `edition` and `entitlements` does not itself grant a capability.
After signature verification, the client applies time, product, app-version,
edition, entitlement, and supported-identity policy before reading local
identity. An unrecognized edition or any
unrecognized entitlement rejects the whole license as
`unsupported_license_policy`; no known subset is exposed, no item is silently
ignored, and no fallback edition is tried. An empty entitlement array is valid
and grants no optional entitlement beyond the recognized edition's documented
baseline. The registry's real production values require a separate product
decision; `beta`, `launch`, and `workflow-export` in Section 18 are synthetic
vector labels, not a production entitlement declaration.

## 7. Canonical JSON decision

### 7.1 Exact SemVer contract

Every app-version field uses SemVer 2.0.0 ASCII grammar: three dot-separated
numeric core identifiers with no leading zero except the single value `0`;
optional `-` prerelease identifiers use `[0-9A-Za-z-]`, with numeric identifiers
also forbidding leading zeros; optional `+` build identifiers use
`[0-9A-Za-z-]`. Empty identifiers and non-ASCII characters are rejected. The
entire text is 1..64 bytes, is case-sensitive, is preserved exactly, and is
never lowercased or otherwise normalized.

Range comparison follows SemVer precedence: compare major/minor/patch
numerically; a prerelease is below its corresponding release; numeric
prerelease identifiers compare numerically and below non-numeric identifiers;
non-numeric identifiers compare by case-sensitive ASCII lexical order; a
shorter equal prefix is lower. Build metadata is allowed and signed/preserved
but ignored for precedence. `max_app_version`, when non-null, must not precede
`min_app_version`; the running app version is parsed and compared by the same
rules.

### 7.2 JSON bytes

The request and unsigned license payload use the same exact rules:

1. Decode bytes as strict UTF-8. Reject a BOM, invalid UTF-8, or trailing data.
2. Parse one top-level JSON object. Use a recursive duplicate-key hook and
   reject every duplicate before semantic processing.
3. Reject every missing or unknown field. Nested objects are not allowed;
   `entitlements` is the only array.
4. Reject floats, exponent forms, `NaN`, `Infinity`, and `-Infinity` during
   parsing. Every numeric field requires `type(value) is int`; Boolean is
   rejected. Integers use the encoder's shortest base-10 form and must satisfy
   field bounds.
5. JSON `null` is allowed only for `max_app_version`. Boolean values are not
   used by either schema.
6. Every string must already be Unicode NFC. The parser rejects rather than
   silently normalizes. Surrogates and all Unicode category `C` code points
   (`Cc`, `Cf`, `Cs`, `Co`, `Cn`) are rejected. Protocol/security identifiers
   are further restricted to ASCII.
7. A producer performs exact schema/type/value validation before emitting. A
   parser first performs the generic JSON type/Unicode rules above, emits the
   candidate canonical form for raw-byte equality, and then performs the exact
   schema/field checks in the version-specific order below. Emission is:

```python
json.dumps(
    value,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
```

8. Emit no spaces, BOM, or leading/trailing newline. Object input order is not
   semantic; array order is semantic, so entitlements must already be sorted
   and unique.
9. On parse, the decoded raw payload bytes must equal the validated object's
   canonical re-encoding byte-for-byte. This rejects alternate key order,
   whitespace, escape spelling, number spelling, and normalization forms.

The JSON dump settings inherit current key sorting, separators, UTF-8, and
`ensure_ascii=False`. Strict input canonicality, duplicate/unknown rejection,
NFC requirements, integer-only values, type/range checks, and size limits are
new-format rules only; they do not rewrite v1 behavior.

## 8. Strict Base64URL and size rules

Every Base64URL segment must be non-empty, contain only
`[A-Za-z0-9_-]`, contain no `=`, whitespace, `+`, or `/`, and have a length
whose remainder modulo four is not one. The decoder adds padding internally
only for decoding, then re-encodes without padding and requires exact equality.
Non-canonical tail bits are rejected.

Encoded limits are checked before decode. Decoding is bounded, and absolute
decoded limits are checked before JSON parse or key lookup. The selected-key
modulus equality check necessarily occurs after exact key lookup but before
RSA verification:

| Limit | Request | License |
|---|---:|---:|
| Entire ASCII container | 4096 bytes | 16384 bytes |
| Encoded payload segment | 2731 ASCII bytes | 10923 ASCII bytes |
| Decoded canonical payload | 2048 bytes | 8192 bytes |
| Signature segment | n/a | 1024 ASCII bytes |
| Decoded signature absolute limit | n/a | 768 bytes |
| Decoded signature/key equality | n/a | exactly the selected RSA key modulus length in bytes |
| Identity value | 512 ASCII bytes | 512 ASCII bytes |

The exact field limits in Sections 5 and 6 also apply. Inputs at a limit are
accepted if otherwise valid; one byte above is rejected. Compression, nested
extension objects, and unbounded arrays are not allowed.

## 9. Canonical signing bytes

Let:

```text
payload_bytes = canonical_json_bytes(unsigned_license_payload)
P = base64url_without_padding(payload_bytes)
signing_bytes = b"LFLIC2." + P.encode("ascii")
```

The RSA PKCS#1 v1.5/SHA-256 signature is calculated over exactly
`signing_bytes`. It is not calculated over the pretty JSON file, decoded JSON
alone, filename, or a reconstructed subset of fields. Because `P` contains the
entire exact-field payload, every payload field is signed. Because `LFLIC2.` is
in the signing bytes, the outer license prefix is also signed.

For requests:

```text
checksum_input = b"LFREQ2." + P.encode("ascii")
C = SHA256(checksum_input).hexdigest()  # 64 lowercase hex
```

This double-binds outer prefix to internal `container_type`,
`container_version`, and `schema`. A prefix/schema/type/version mismatch is
always an error even if a payload or signature is otherwise valid.

## 10. Prefix and schema dispatch

Dispatch uses an exact prefix table, never appearance or fallback guessing:

| Prefix/container | Required internal binding |
|---|---|
| `LFREQ1` | current `lfreq-1`; permanent `legacy-v1` semantics |
| unprefixed legacy request | explicit legacy parser only; permanent `legacy-v1` semantics |
| `LFREQ2` | `container_type=request`, `container_version=2`, `schema=lfreq-2` |
| current JSON `lflic-1` | permanent `legacy-v1` semantics |
| unversioned legacy license JSON | permanent `legacy-v1` semantics |
| `LFLIC2` | `container_type=license`, `container_version=2`, `schema=lflic-2` |

An unknown prefix is never passed to a legacy parser. A known-prefix error
terminates that parser path; it cannot fall through to another version.
`LFREQ2` cannot wrap `lfreq-1`, and `LFLIC2` cannot wrap `lflic-1`. Request and
license payloads cannot be exchanged. No unsigned version hint overrides the
signed/checked payload.

### 10.1 Request parsing and admin-review order

A future `LFREQ2` parser/admin must use this order:

1. require an exact single line, `LFREQ2`, three segments, total limit, encoded
   payload limit, and checksum-segment length without trimming;
2. require a strict Base64URL payload segment and exact 64-lowercase-hex
   checksum syntax; bounded-decode `P`, then enforce the absolute decoded
   payload limit;
3. recompute `SHA256(b"LFREQ2." + P)` and compare the checksum in constant time
   before JSON decoding;
4. decode strict UTF-8 JSON and reject duplicate keys;
5. require raw bytes to equal canonical re-encoding;
6. validate exact fields/types/ranges and exact prefix/type/version/schema/
   product binding;
7. require a supported request identity algorithm for the explicitly selected
   admin issuance mode; admin never invokes a local identity resolver;
8. apply future-time and age review, then require administrator-side persistent
   replay/authorization state for `(schema, request_id)` and explicit human
   ownership/entitlement approval. UUID/time/checksum alone never authorize
   issuance.

A failure is terminal for `LFREQ2` and never enters `LFREQ1` or unprefixed
legacy parsing. Checksum validation occurs before JSON for a stable damage
error and bounded parse cost, but the checksum remains forgeable.

## 11. License validation order

A future `LFLIC2` client must use this order:

1. Check the total ASCII container length, exact three-segment framing, and
   case-sensitive `LFLIC2` prefix.
2. Check the encoded payload and signature-segment lengths.
3. Apply strict, bounded, unpadded Base64URL decoding and enforce the absolute
   decoded payload/signature limits.
4. Decode strict UTF-8 JSON with recursive duplicate-key rejection.
5. Require decoded raw payload bytes to equal canonical re-encoding.
6. Validate the exact field allowlist, required fields, types, bounds, and
   prefix/container-type/container-version/schema binding. Syntax checks at
   this stage do not make unsigned selectors trusted.
7. Require the exact `(signing_algorithm, key_id)` pair to exist in the bounded
   trusted key registry and select only that entry. Unknown pairs fail closed.
8. Require decoded signature length to equal the selected entry's trusted RSA
   modulus byte length. Length mismatch rejects; it never selects another key.
9. Verify the RSA signature over `b"LFLIC2." + P`. Invalid signatures fail
   before any local identity source is touched.
10. Only after a valid signature, validate all signed semantics that do not
    depend on local identity: container type/version, payload schema, product,
    license ID, request correlation, `issued_at`/`expires_at`, min/max app
    version, edition, sorted/unique entitlement allowlist, and whether the one
    signed identity algorithm is explicitly supported.
11. Reject an expired, not-yet-effective, wrong-product, app-version-
    incompatible, unsupported-edition, unsupported-entitlement, or unsupported-
    identity-algorithm license without reading local hardware identity. The
    time rule is `issued_at <= now < expires_at`; every unknown policy value
    rejects the whole license.
12. Only after every signed non-identity constraint succeeds, select the unique
    resolver named by the signed identity algorithm.
13. Acquire local identity exactly once. Provider failure is an identity error;
    it is not retried or relabeled as a signature/policy failure.
14. Apply that algorithm's canonicalization and perform one timing-safe exact
    comparison with the signed `identity_value`.
15. On mismatch, do not try another algorithm, candidate, partial match,
    `legacy-v1` path, or error-triggered fallback.
16. Expose entitlements only after identity success and every preceding check.

The explicit LFLIC2 invariants are **signature-before-identity**,
**policy-before-identity**, **expiry-before-identity**, and
**app-version-before-identity**. Identity is collected exactly once, and
entitlements are exposed only after identity success. This is the recommended
order only for the new `LFLIC2` design. It does not modify the frozen `lflic-1`
or unversioned legacy validation order in Section 4.3 or any production
behavior.

## 12. Compatibility matrix

| Tool combination | Required result |
|---|---|
| old client + old license | unchanged current validation |
| old client + `LFLIC2` | fail closed as unreadable/non-JSON; no partial license acceptance |
| new client + old license | explicit old parser and permanent `legacy-v1` resolver |
| new client + `LFLIC2` | exact v2-container path; signature or signed time/product/version/policy/algorithm failure reads identity zero times and never falls back |
| old admin + old request | unchanged current behavior |
| old admin + `LFREQ2` | fail closed; current broad legacy attempt must not yield a JSON object or partial request |
| new admin + old request | only explicit `legacy-lflic-1` issuance; both `LFREQ1` and unprefixed legacy requests produce `lflic-1` |
| new admin + `LFREQ2` | explicit v2-container issuance only, producing `LFLIC2` with the same identity pair |

The new admin starts in inspect-only mode. It requires exact explicit modes:
`legacy-lflic-1` or `versioned-lflic-2`, and never defaults to either.
`legacy-lflic-1` is the only recommended new-admin output for both kinds of old
request; the request shape never guesses a target license schema. New-admin
issuance of the older unversioned license is not part of this design and would
need a separate explicit compatibility decision/mode. The admin cannot convert
an old request to `LFLIC2` or a new request to `lflic-1`; an operator must ask
the client for the required request format. A new client never interprets an
unknown prefix as legacy. An `LFLIC2` error never enters the v1 verifier.

## 13. Identity binding decision

- `LFREQ1`, legacy requests, `lfreq-1`, `lflic-1`, and unversioned licenses
  always select the exact frozen `legacy-v1` algorithm.
- A versioned request carries one authoritative `identity_algorithm` and one
  `identity_value`; the admin copies the pair and does not recompute it.
- A versioned signed license carries the same one pair inside signed payload
  bytes. No outer or local preference can override it.
- One signed license selects one resolver. Candidate arrays, match-any,
  heuristic length/case detection, silent legacy fallback, and client-selected
  downgrade are forbidden.
- The resolver is selected only after signature and every signed non-identity
  time/product/version/policy/support constraint succeeds. It is called exactly
  once; mismatch or provider failure never selects a second resolver.
- A deliberately signed `legacy-v1` value in a future container is explicit
  authorization, not fallback; it must require an explicit issuance mode and is
  not the recommended migration default.
- Recovery uses a new request, human approval, and a new license, not relaxed
  local comparison.

## 14. Downgrade and parser threat model

| Threat | Attacker capability | Current v1 behavior | New defense | Residual risk | Required test |
|---|---|---|---|---|---|
| Prefix substitution | edit/cross-swap outer text | request prefix not checksum-bound; license has none | request checksum and license signature bind exact prefix; internal binding exact | request remains forgeable | byte change and request/license prefix swap reject |
| Schema substitution | replace schema/version | current schemas checked; license schema signed | exact type/version/schema plus signed/checked prefix binding | request attacker can recompute checksum | old/new schema and version mismatches reject |
| Identity field stripping | remove algorithm or value | v1 algorithm is implicit | both fields required; license signs both | none after valid signature | delete each field; resolver count zero |
| Identity downgrade | change future algorithm to legacy | v1 has no version | signed exact pair and per-client allowlist; no fallback | issuer can deliberately sign legacy | mutation invalidates signature; unsupported stays unsupported |
| Candidate-ID injection | add aliases/arrays | unknown fields accepted but current client uses one ID | exact keys and one pair | issuer can sign a wrong single value | `candidate_ids`/aliases rejected; one resolver call |
| Unknown-field smuggling | exploit parser/signer disagreement | request/license unknown keys accepted | exact allowlist at every object | extension needs a new schema | top-level and nested unknowns reject |
| Duplicate JSON keys | exploit last-key-wins differences | standard JSON last-key-wins | recursive duplicate rejection before semantics | cross-language drift if untested | duplicates of every security field reject |
| Unsigned outer metadata | alter algorithm/key/type hints | request prefix unauthenticated; no license outer container | only prefix outside payload; prefix signed for license; all selectors signed | filename remains unsigned and meaningless | sidecar/header cannot affect dispatch |
| Signature swapping | move signature between payloads/prefixes | v1 payload mutation fails but has no domain prefix | sign exact `LFLIC2.<P>` plus signed key/algorithm | same payload/signature copy is equivalent | payload/signature/key swaps reject |
| Request replay | resubmit approved request | request ID/history can detect duplicates but can be forced | persistent administrator-side processed-ID and authorization state; atomic check-and-record before issuance | missing/rolled-back state or a forged fresh ID; first-seen is not ownership proof | duplicate/conflicting ID, unavailable state, old/future claims, and fresh forged ID |
| Request forgery | synthesize identity and checksum | v1 checksum offers no authenticity | UI/admin explicitly treat request as unauthenticated; human approval | forgery remains possible offline | recomputed checksum still never auto-issues |
| License replay/clone | copy valid signed license | same ID accepts; no revocation/anti-copy | exact ID/expiry/license ID remain signed | identical-ID clone/VM snapshot remains possible | different ID rejects; clone limit documented |
| Old-admin legacy issuance | feed new request to old tool | broad legacy decoder is attempted | prefix chosen so old decode cannot become JSON; fixed compatibility vector | old error is generic | complete synthetic `LFREQ2` rejected by old behavior |
| New-admin auto downgrade | trigger errors/old mode | no new admin exists | inspect-only default; explicit `legacy-lflic-1` or `versioned-lflic-2`; no inferred/unversioned output | operator can request a new legacy request | complete issuance-mode matrix |
| New-license v1 fallback | damage new license then seek old path | no new format exists | prefix router is single-path and terminal | none | bad signature/schema/ID calls legacy zero times |
| Entitlement mutation | add/remove/reorder rights | current features signed but loosely typed | sorted unique signed tokens; any unknown policy value rejects the whole license | issuer policy can over-grant | add/remove/duplicate/reorder/invalid/unknown token |
| Expiry mutation | extend or invert time | v1 times signed but parse is broad | signed bounded epoch integers and strict interval | offline clock rollback remains | boundary, Boolean/float, negative, inverted interval |
| Product/edition mutation | cross-product or elevate edition | signed, with loose edition semantics | exact signed product and bounded signed edition | issuer configuration error | mutation changes bytes/signature; policy reject unknown edition |
| Oversized-token DoS | send huge segments/objects | no v1 size limits | pre-decode wire/segment and decoded/field/count limits | bounded CPU work remains | limit, limit+1, and huge undecoded input |
| Malformed Unicode | use invalid UTF-8, controls, NFD, bidi | no NFC/control policy | strict UTF-8, already-NFC strings, category-C rejection | visual confusables may remain in customer name | NFC/NFD, surrogate, bidi, control fixtures |
| Base64URL ambiguity | use alternate alphabet/tail bits | LFREQ1 decode is permissive | strict alphabet, no whitespace, canonical round trip | none | `+`, `/`, ignored chars, bad tail bits reject |
| Padding ambiguity | add/remove `=` | request emitter strips but parser may accept; license uses padded standard Base64 | all new segments are unpadded strict Base64URL | none | every extra-padding form rejects |
| Key/algorithm confusion | choose weak algorithm or default key | v1 hardcodes one algorithm/key | exact signed pair in a bounded trusted registry; key ID is full SPKI digest and never a path/URL; no length guessing/default/try-all/fallback | installed client cannot learn offline revocation | unknown pair/path-like ID/length mismatch/wrong-key signature all reject before identity |
| Numeric/parser differential | use bool, float, NaN, exponent, huge int | current coercion/default JSON is loose | exact integer type/bounds, float/constants rejected, canonical raw equality | other implementations must reproduce tests | all alternate numeric forms reject |
| Identity-before-trust oracle | make a bad artifact read host identity | current v1 valid signature precedes identity and then expiry/version | LFLIC2 checks signature plus signed time/product/app-version/edition/entitlement/algorithm policy before one resolver read | an otherwise valid device mismatch/provider error still requires one read | invalid frame/schema/key/signature or signed policy/time/version failure reads zero; fully eligible match/mismatch reads exactly once |
| Clock rollback | change local time | can revive an offline license | exact epoch removes parsing ambiguity only | trusted time is unavailable offline | document residual; no anti-rollback claim |
| Key compromise/revocation | sign with stolen trusted key | one embedded key, no key ID | exact key ID supports bounded rotation | installed offline clients need an update/revocation policy | multi-key allowlist and removed/unknown ID cases |
| Reissue abuse | edit old payload or use partial match | reissue requires another signature | new request, approval, new ID, immutable audit; no override/match-any | support/revocation limits undecided | lost-ID reissue and original-artifact independence |

## 15. Migration policy

1. Never rewrite an old license.
2. Every old format remains independently verifiable through its exact
   `legacy-v1` path for its supported lifetime.
3. A client upgrade does not migrate a license. A new request does not mutate
   or invalidate the old artifact.
4. New admin issuance modes are explicit. `legacy-lflic-1` converts either
   supported old request shape only to `lflic-1`; `versioned-lflic-2` converts
   `LFREQ2` only to `LFLIC2`. No request shape selects a mode automatically.
5. No default mode silently signs legacy, no parser converts across generations,
   and no unsigned downgrade override exists.
6. No raw identity parts are recovered from logs, no signed payload is edited,
   and no partial identity match is accepted.

Support duration, revocation, ownership proof, issuance quotas, duplicate-device
policy, and old-license retirement remain separate product decisions.

## 16. Reissue and reactivation policy

If a legacy ID cannot be reproduced after reinstall, permission, locale,
hostname/account, disk, VM, clone, or hardware change:

1. the user generates a new request in a supported format;
2. support displays masked request/version information and verifies ownership
   and entitlement outside the unauthenticated token;
3. an operator explicitly approves a reissue;
4. admin creates a new license ID, preserves request correlation, and appends an
   immutable audit record linking the superseded license when known;
5. the client validates the new artifact through only its named algorithm.

The old signed artifact is not edited. Reactivation never uses raw-parts log
reconstruction, candidate matching, partial fields, local overrides, or a
signature bypass.

## 17. Rollback policy

Rolling back to an old client requires re-importing the original compatible old
license. An old client is not expected to read `LFLIC2`, and a new license is
never converted to an old one. A new client that supports both generations
keeps separate parser/resolver paths. Removing a not-yet-released v2-container
implementation must leave every v1 path and old artifact unchanged.

Rollback cannot mean deleting an identity-version field, retrying with
`legacy-v1`, trying every known ID, or accepting an unsigned override.

## 18. Synthetic reference vectors

Every value in this section is a **non-production synthetic design vector**.
No signature is present, no key is used, no current parser-accepted token is
printed, and the repeated `A` identity is not a real device identifier.

### 18.1 Request payload

```json
{
  "container_type": "request",
  "container_version": 2,
  "schema": "lfreq-2",
  "product": "launchflow",
  "app_version": "0.1.0-beta.2",
  "request_id": "00000000-0000-4000-8000-000000000001",
  "created_at": 1767225600,
  "identity_algorithm": "legacy-v1",
  "identity_value": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```

Canonical UTF-8 text (no trailing newline):

```text
{"app_version":"0.1.0-beta.2","container_type":"request","container_version":2,"created_at":1767225600,"identity_algorithm":"legacy-v1","identity_value":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","product":"launchflow","request_id":"00000000-0000-4000-8000-000000000001","schema":"lfreq-2"}
```

- canonical payload SHA-256:
  `116218713468c1615ad89d95a1fa3fd43938d9ae88c777dbed6d99ce43adeb2c`
- prefix-bound request checksum:
  `836771f1261aae50e88eb35ace56a36a7c1e36d8d03f3ac88273dd388d057250`

The object rebuilt in reverse insertion order produces the same canonical
bytes. This vector exercises explicit `legacy-v1` carriage only; it does not
recommend legacy issuance as a migration default and does not define HWID v2.

### 18.2 Unsigned license payload

```json
{
  "container_type": "license",
  "container_version": 2,
  "schema": "lflic-2",
  "signing_algorithm": "rsa-pkcs1v15-sha256",
  "key_id": "spki-sha256:0000000000000000000000000000000000000000000000000000000000000000",
  "license_id": "00000000-0000-4000-8000-000000000002",
  "request_id": "00000000-0000-4000-8000-000000000001",
  "product": "launchflow",
  "identity_algorithm": "legacy-v1",
  "identity_value": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  "customer": "测试用户",
  "edition": "beta",
  "entitlements": ["launch", "workflow-export"],
  "issued_at": 1767225600,
  "expires_at": 1798761600,
  "min_app_version": "0.1.0-beta.2",
  "max_app_version": null
}
```

Canonical UTF-8 text (no trailing newline):

```text
{"container_type":"license","container_version":2,"customer":"测试用户","edition":"beta","entitlements":["launch","workflow-export"],"expires_at":1798761600,"identity_algorithm":"legacy-v1","identity_value":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","issued_at":1767225600,"key_id":"spki-sha256:0000000000000000000000000000000000000000000000000000000000000000","license_id":"00000000-0000-4000-8000-000000000002","max_app_version":null,"min_app_version":"0.1.0-beta.2","product":"launchflow","request_id":"00000000-0000-4000-8000-000000000001","schema":"lflic-2","signing_algorithm":"rsa-pkcs1v15-sha256"}
```

- canonical payload SHA-256:
  `5213820461142872a6275b0c98f2e4db5c4004f11a5c50faee08fbdb8f64cf2c`
- canonical signing-bytes SHA-256:
  `e2fa2e92eb8a11a9d1ef69fb87b42f3729e769e6f4d0d941419d31e0cccf82c6`
- deliberately invalid placeholder signature:
  `<NON-PRODUCTION-SIGNATURE>`

The Unicode customer proves `ensure_ascii=False`; `max_app_version: null` is
the empty optional-field fixture. Reversed object insertion order produces the
same bytes. A valid change to any of container type/version/schema,
signing algorithm/key ID, identity pair, product, edition, entitlement,
validity, license ID, or request ID changes the signing bytes.

### 18.3 Negative vectors

| Fixture | Required result |
|---|---|
| unknown top-level field | reject before checksum/signature semantics |
| duplicate `schema` key | reject during strict JSON parse |
| `LFREQ2` with `lfreq-1`, or `LFLIC2` with `lflic-1` | prefix/schema mismatch; reject |
| request payload presented as license | container-type mismatch; reject |
| invalid signature, not-yet-effective/expired time, wrong product, incompatible app version, unknown edition/entitlement, or unsupported identity algorithm | reject before local identity; zero identity reads |
| identity/customer/entitlement one byte above limit | reject before signature/key work |
| NFD customer spelling or category-C character | reject; do not normalize silently |
| Boolean/float timestamp | reject exact type |
| padded or non-canonical Base64URL | reject before JSON parse |

## 19. Minimum future implementation review

The next task may review—but must not automatically publish—the smallest
implementation slice:

1. pure strict JSON/Base64URL/framing value types with these fixed vectors;
2. explicit parser dispatch that keeps every current v1 path untouched;
3. v2-container request inspection and inspect-only admin behavior;
4. license verification with prefix-bound signing bytes, an exact trusted
   `(signing_algorithm, key_id)` registry, all signed non-identity gates before
   identity, and an injected resolver registry;
5. explicit issuance modes and downgrade/compatibility tests;
6. no new identity algorithm and no default production issuance until a
   separate Phase 1m decision supplies real-host evidence and product policy.

That review must protect all current parser/schema/signer/HWID files, use only
synthetic keys if signing tests are separately authorized, and retain signature
plus every signed non-identity policy/support gate before exactly one identity
acquisition. It is not release authorization.

## 20. Remaining design risks

- Offline requests are forgeable; checksums cannot authenticate a device or
  owner.
- Administrator-side persistent request-ID/authorization state is an
  implementation requirement and is not implemented. Even when implemented,
  it detects processed IDs but cannot authenticate a fresh forged request.
- A copied license can work on another environment that reproduces the same
  identity, including some clones or VM snapshots.
- Offline validation cannot reliably detect system-clock rollback or learn
  key/license revocation without another trusted channel.
- `key_id` enables exact rotation selection but does not repair compromise in
  already installed offline clients.
- Trusted key lifecycle, the concrete recognized edition/entitlement registry,
  request history retention, revocation, reissue limits, and ownership proof
  need separate implementation/product decisions; unknown policy values are
  nevertheless already frozen as whole-license fail-closed.
- HWID v2 inputs, normalization, privacy, collision, spoofing, reinstall,
  permission, VM/container/clone, and real Windows/Linux/macOS host behavior
  remain entirely undefined and unimplemented.
