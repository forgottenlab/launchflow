# LaunchFlow Hardware Identity Contract Audit

## 1. Scope and result

Phase 1i is a compatibility and privacy audit. It adds no provider, changes no
identity source, and changes no `LFREQ1`, `lflic-1`, RSA, activation, or license
verification behavior. Windows x86_64 remains the only supported Beta target.

All executable evidence uses synthetic constants and dependency replacement.
The audit never queries the host registry, starts the volume command, reads the
host name or account name, generates a client request code, signs a license, or
loads key material. A stable hash is treated as a persistent device identifier,
not anonymous data.

## 2. Current call chain

Client display and request flow:

```text
ActivationWindow
  -> ActivationService.get_display_machine_id()
       -> licensing.hwid.get_machine_id()
            -> licensing.hwid.get_machine_fingerprint_parts()
                 -> shared.platform.identity HardwareIdentityProvider.collect_parts()
                 -> HardwareIdentityParts.to_legacy_dict()
            -> shared.platform.identity.build_legacy_v1_machine_id(parts)
       -> licensing.hwid.format_machine_id()
  -> ActivationService.generate_request_payload()
       -> licensing.request_token.build_request_payload(machine_id)
  -> ActivationService.generate_request_code()
       -> licensing.request_token.encode_request_token(payload)
```

License verification flow:

```text
editor.main / ActivationWindow
  -> LicenseManager.validate_current_license()
  -> LicenseManager.validate_license_data()
       -> verify_signature(payload without signature)
       -> licensing.hwid.get_machine_id()
       -> uppercase current ID == stripped/uppercase license machine_id
       -> expiry and version checks
```

Author-side tools do not recompute device identity. They parse the request and
copy its stripped, uppercased `machine_id` into the license payload. Both the
current admin core and the older generator follow that binding. The client then
recomputes its local ID and compares it after signature verification.

## 3. Frozen public surface

| Symbol | Signature | Current return |
|---|---|---|
| `_read_windows_machine_guid` | `() -> str` | stripped value or `""` |
| `_read_machine_sid_fallback` | `() -> str` | pipe-joined non-empty source values |
| `_read_volume_serial` | `() -> str` | complete stripped command stdout or `""` |
| `get_machine_fingerprint_parts` | `() -> Dict[str, str]` | ordered five-field dictionary |
| `get_machine_id` | `() -> str` | 64-character uppercase SHA-256 hex |
| `format_machine_id` | `(machine_id: str, group: int = 4) -> str` | alphanumeric uppercase groups joined by `-` |

No identity algorithm or schema version is exposed by these APIs.

## 4. Input and call-order contract

`get_machine_fingerprint_parts()` performs these operations in order:

1. read the Windows machine GUID;
2. read the system-volume command output;
3. build fallback data from, in order:
   `platform.system()`, `platform.release()`, `platform.version()`,
   `socket.gethostname()`, and `getpass.getuser()`;
4. read `sys.version.split()[0]`;
5. read `platform.platform()`.

The returned dictionary insertion order is:

1. `machine_guid`
2. `volume_serial`
3. `fallback`
4. `python`
5. `platform`

All three primary inputs are collected on Windows. The fallback is not used
only when stronger sources fail; it always participates in the current hash.
Consequently host name, account name, OS release, or OS version changes can
invalidate a Windows license even when the registry and volume values remain
available.

The `python` and `platform` dictionary values are observable through the parts
API but do **not** participate in the final hash. Changing Python version alone
or the `platform.platform()` display string alone therefore does not change the
current machine ID.

## 5. MachineGuid behavior

- The Windows branch is selected by exact `os.name == "nt"`.
- `winreg` is imported only inside the reader after that branch check.
- Hive: `HKEY_LOCAL_MACHINE`.
- Key: `SOFTWARE\Microsoft\Cryptography`.
- Value name: `MachineGuid`.
- The value is converted with `str(value).strip()`; there is no case conversion,
  UUID parsing, format validation, or canonical UUID normalization.
- A blank/whitespace value becomes an empty string.
- `FileNotFoundError`, `PermissionError`, `OSError`, import failures, query
  failures, and every other `Exception` become an empty string.
- Non-Windows returns an empty string without importing `winreg`.

The reader does not surface why the value is missing. A temporary access failure
therefore changes the serialized input instead of producing a distinguishable
identity-source error.

## 6. Volume serial behavior

- The Windows branch is selected by exact `os.name == "nt"`.
- The exact call is `execute_command("vol C:", "cmd")`.
- Execution goes through `runtime.command_runner`, which consumes the current
  `CommandBackend` and returns decoded stdout/stderr/return code.
- The HWID reader uses only `result.stdout or ""`, followed by `.strip()`.
- It does not parse a serial number. The value named `volume_serial` is the
  complete stripped stdout, including localized labels and internal newlines.
- Return code, stderr, `launch_error`, and `error_kind` are ignored.
- Nonzero return code with non-empty stdout still contributes that stdout.
- Empty/`None` stdout becomes an empty string.
- Any exception escaping `execute_command` becomes an empty string.
- Non-Windows returns an empty string without launching a command.

Windows output decoding currently tries the preferred locale encoding and then
the backend fallbacks (`utf-8`, `mbcs`, `cp936`, with duplicates skipped). A
locale, wording, decoding, or line-ending change can therefore change the HWID
even if the human-readable serial portion is unchanged.

## 7. Fallback behavior

Fallback values are joined with one literal `|`. Falsy values are omitted;
truthy values are converted with `str()` and preserved exactly. There is no
strip, case normalization, Unicode normalization, escaping, field name, or
length prefix. Embedded `|`, spaces, case, and Unicode remain part of the raw
fallback string.

Errors from platform, host-name, or user-name sources are not caught here and
propagate through `get_machine_fingerprint_parts()` and `get_machine_id()`.

On Linux, macOS, and unknown systems the first two hash fields are empty and
the legacy fallback is the only identity material. This behavior is frozen for
compatibility but is not considered stable or supported native identity.

## 8. Serialization and hash contract

Only three dictionary values are serialized, in this exact order:

```text
machine_guid + "||" + volume_serial + "||" + fallback
```

Missing dictionary keys default to empty strings. Empty fields remain visible
through the fixed separators; three empty values serialize as four pipe
characters. Values are not stripped or normalized again at the hash boundary.

The exact digest contract is:

- encoding: UTF-8;
- algorithm: SHA-256;
- representation: `hexdigest()`;
- case: uppercase;
- length: 64 characters;
- truncation: none;
- prefix/version marker: none;
- salt/secret: none.

`format_machine_id()` is display-only. It removes non-alphanumeric characters,
uppercases the result, and groups from left to right using the requested group
size. It is not used for request or license comparison.

## 9. Synthetic compatibility fixtures

The primary Windows fixture uses visibly synthetic sources:

- GUID source: `SYNTHETIC_GUID` in the smoke;
- volume source: `ABCD-1234`;
- host: `TEST-HOST`;
- account: `TestUser`;
- fallback: `Windows|11|10.0.26100|TEST-HOST|TestUser`.

Its frozen SHA-256 result is:

```text
92FD6B08959D22BC7EB9FEC57E6471C701CB7BDE158D48128D6BC403666DAC4D
```

The smoke also freezes synthetic Linux, macOS, and unknown legacy results,
registry failures, command failures, empty values, localized/multiline stdout,
Unicode/space/case/special-character fallback inputs, and repeated deterministic
calculation. Changing any of the three serialized fields changes the fixture
digest; changing only `python` or `platform` does not.

## 10. Request and license binding

`build_request_payload()` strips and uppercases the supplied machine ID and
places it at the `machine_id` key in the `lfreq-1` payload. `LFREQ1` is Base64URL
canonical JSON plus a checksum; it is not encrypted or authenticated. Anyone
holding a request code can decode the persistent machine ID.

`build_license_payload()` copies the request machine ID after the same
strip/uppercase normalization into the `lflic-1` payload. The RSA signature
covers that payload. The legacy license format also stores `machine_id` and is
accepted by the current client.

`LicenseManager` verifies the signature before computing local identity. It
then compares `current_machine_id.upper()` with the license value after
`str(...).strip().upper()`. This is a direct identifier comparison, not another
hash comparison and not a comparison of raw source fields. A mismatch returns
`machine_not_match`.

Neither request nor license schema records the HWID algorithm/version, source
availability, platform, or architecture. Current schema versions identify the
request/license containers, not the identity algorithm.

## 11. Privacy assessment

| Data | Privacy classification | Current exposure boundary |
|---|---|---|
| Registry value | Stable device source | Must remain process-local; never log or document real values |
| Complete volume stdout | Device and locale/environment data | Must remain process-local; may include labels and serial text |
| Host name | Device/environment identifier | Participates in every current hash, including Windows |
| Account name | Personal/environment identifier | Participates in every current hash, including Windows |
| OS release/version | Environment fingerprint | Participates in every current hash |
| 64-character HWID | Persistent device identifier | Displayed in activation UI, embedded in request/license payloads |
| Request code | Reversible transport containing HWID | Explicit user copy/send action; not confidential encryption |
| License payload | Persistent signed HWID storage | Stored in the local license file and author-issued artifact |

Hashing lowers direct raw-field exposure but does not anonymize the result. The
unsalted stable digest remains linkable across requests, licenses, support
records, backups, and installations that produce the same inputs.

Current source behavior observed by this audit:

- the activation UI intentionally displays the complete grouped HWID and the
  complete request code;
- the clipboard button copies the request code after an explicit user action;
- normal startup logs record only the license result code, not the HWID;
- the diagnostics redactor masks labelled machine/request/signature values and
  recognizable request tokens, but an unlabelled raw 64-character digest is not
  inherently detectable;
- the current author admin inspect/history paths mask machine IDs;
- the older interactive generator can display the full machine ID and therefore
  remains a manual operational privacy risk;
- `get_machine_fingerprint_parts()` exposes raw source fields to callers and
  must never be added to logs, diagnostics, crash reports, or support output.

Repository docs/tests may contain only clearly labelled synthetic values. They
must never contain real source fields, HWIDs, request/license artifacts,
signatures, key material, local license contents, or user-specific paths.

## 12. Compatibility risk matrix

There is no alternate-identity verification path today. “Fallback exists” below
means a source can become empty or the generic fallback is present; it does not
mean an old license can still match after the serialized input changes.

| Change/failure | Current HWID impact | Existing license | Current fallback | Risk | Versioned migration needed |
|---|---|---|---|---|---|
| Windows reinstall | Likely changes registry, OS and possibly volume text | Likely invalid | Generic fallback is still changed/included | High | Yes |
| MachineGuid changes | First serialized field changes | Invalid | Empty/string fallback cannot match old ID | High | Yes |
| System disk replacement | Volume output and possibly OS inputs change | Likely invalid | No alternate verification | High | Yes |
| Volume format | Volume output changes | Invalid | No alternate verification | High | Yes |
| Volume serial/output changes | Second serialized field changes | Invalid | No alternate verification | High | Yes |
| Account name changes | Always-included fallback changes | Invalid | None | High | Yes |
| Host name changes | Always-included fallback changes | Invalid | None | High | Yes |
| OS release/version upgrade | Always-included fallback can change | Likely invalid | None | High | Yes |
| Python version changes only | Parts metadata changes, hash input does not | Remains valid | Not applicable | Low | No for legacy v1 |
| `platform.platform()` changes only | Parts metadata changes, hash input does not | Remains valid | Not applicable | Low | No for legacy v1 |
| VM clone | Clone may retain every source | Same HWID may be duplicated | No clone detection | High | Yes, plus policy |
| Disk-image restore | Restored sources may reproduce old HWID | May remain valid or diverge | No provenance check | Medium | Yes |
| Registry permission denied | Registry field becomes empty | Invalid if previously present | Exception is silently empty | High | Yes |
| Registry value missing | Registry field becomes empty | Invalid if previously present | Exception is silently empty | High | Yes |
| Volume command unavailable | Volume field becomes empty | Invalid if previously present | Exception/empty stdout is silently empty | High | Yes |
| Nonzero command with stdout | Full stdout still participates | Depends on exact text | Return code ignored | High | Yes |
| Localized volume output changes | Complete second field changes | Invalid | No parser/canonical serial | High | Yes |
| Linux system upgrade | release/version fallback changes | Invalid | Legacy fallback only | High | Yes before support |
| Linux host/account rename | fallback changes | Invalid | Legacy fallback only | High | Yes before support |
| macOS system upgrade | release/version fallback changes | Invalid | Legacy fallback only | High | Yes before support |
| macOS host/account rename | fallback changes | Invalid | Legacy fallback only | High | Yes before support |

## 13. Phase 1i design and Phase 1k extraction status

Phase 1i recorded the following design without implementing it. Phase 1k now
implements that exact behavior-equivalent legacy-v1 boundary in
`shared/platform/identity.py`:

```text
frozen HardwareIdentityParts
  - machine_guid
  - volume_serial
  - fallback
  - python
  - platform

HardwareIdentityProvider Protocol
  - platform_info
  - collect_parts() -> HardwareIdentityParts

WindowsHardwareIdentityProvider
  - delayed registry source
  - injected command runner
  - injected platform/host/user sources

LegacyPosixHardwareIdentityProvider
  - exact legacy source behavior only
  - no native-support claim
```

The provider collects inputs only. Legacy-v1 fallback construction,
serialization, and hashing are separately named pure compatibility functions
with the exact current field order, separators, UTF-8, and SHA-256 output. The
Windows command executor is injected from `licensing/hwid.py`, so the platform
module does not import runtime. The six existing facade/helper signatures and
their monkeypatch seams remain in `licensing/hwid.py`; each machine-ID call
performs one fresh parts collection and no result is cached.

A future algorithm must be versioned and computed in parallel, not substituted
in place. Current requests and licenses have no identity-version field, so they
must always select legacy v1 verification. A new request/license container
version, or another explicitly signed compatible extension, is required before
a new identity version can be bound safely. Existing canonical payloads must not
gain fields in place.

Future implementation gates must include:

- explicit legacy-v1 verification for every existing license format;
- a declared new-version source/serialization/collision policy;
- reactivation and support recovery for changed hardware/source permissions;
- no silent multi-identity acceptance that weakens device binding;
- minimum-data collection and masked audit events;
- no raw parts or complete stable identifier in logs/diagnostics;
- synthetic fixtures for every version and transition;
- real Windows validation for reinstall/disk/permission/locale/VM cases;
- real Linux and macOS validation before native issuance or support claims;
- rollback that leaves current Windows v1 verification authoritative.

## 14. Legacy-license migration requirement

Any direct replacement of the current hash would make already issued legacy and
`lflic-1` licenses fail machine comparison. The safe sequence is:

1. continue computing legacy v1 exactly for every existing license;
2. introduce an explicitly versioned request and signed license contract for a
   future algorithm;
3. decide whether eligible users receive a dual-bound transition license or a
   controlled reissue after identity changes;
4. keep verification paths separate and auditable;
5. provide recovery/reissue policy before changing issuance defaults;
6. remove legacy verification only through a separately approved end-of-support
   decision, never as an incidental provider refactor.

Phase 1k implements only the behavior-equivalent legacy-v1 provider extraction.
The Phase 1i fixed synthetic digest, HWID algorithm, request/license schemas,
RSA flow, and every old-license interpretation remain unchanged. HWID v2,
request/license migration, native Linux/macOS identity, and license migration
remain not implemented and require separate authorization.
