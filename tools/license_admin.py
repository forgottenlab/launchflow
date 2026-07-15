"""Author-only LaunchFlow License Admin CLI (phase 1)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from licensing.request_token import mask_machine_id, parse_request_token
from tools.license_admin_core import issue_license, load_history, verify_license_file


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "generated_licenses"
DEFAULT_HISTORY_FILE = DEFAULT_OUTPUT_DIR / "license_admin_history.jsonl"
DEFAULT_DEV_LICENSE_DAYS = 1095


def _add_request_source(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", help="LFREQ1 or legacy request token")
    source.add_argument("--request-stdin", action="store_true", help="read one request token from stdin")


def _read_request(args: argparse.Namespace) -> dict:
    token = sys.stdin.read().strip() if args.request_stdin else str(args.request).strip()
    return parse_request_token(token)


def _print_request(payload: dict) -> None:
    print(f"schema={payload.get('schema')}")
    print(f"product={payload.get('product')}")
    print(f"client_version={payload.get('app_version')}")
    print(f"request_id={payload.get('request_id')}")
    print(f"created_at={payload.get('created_at')}")
    print(f"machine_id={mask_machine_id(str(payload.get('machine_id', '')))}")
    print(f"legacy={'true' if payload.get('legacy') else 'false'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LaunchFlow author-only license administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="inspect a request without issuing")
    _add_request_source(inspect_parser)

    issue_parser = subparsers.add_parser("issue", help="issue a signed license after manual approval")
    _add_request_source(issue_parser)
    issue_parser.add_argument("--customer", required=True)
    issue_parser.add_argument("--edition", required=True)
    issue_parser.add_argument("--days", required=True, type=int)
    issue_parser.add_argument("--feature", action="append", default=[])
    issue_parser.add_argument("--min-app-version")
    issue_parser.add_argument("--max-app-version")
    issue_parser.add_argument("--private-key", type=Path)
    issue_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    issue_parser.add_argument("--history-file", type=Path)
    issue_parser.add_argument("--force", action="store_true")

    issue_dev_parser = subparsers.add_parser(
        "issue-dev",
        help="issue a signed, machine-bound developer license to an explicit path",
    )
    _add_request_source(issue_dev_parser)
    issue_dev_parser.add_argument("--customer", default="LaunchFlow Developer")
    issue_dev_parser.add_argument("--days", type=int, default=DEFAULT_DEV_LICENSE_DAYS)
    issue_dev_parser.add_argument("--feature", action="append", default=[])
    issue_dev_parser.add_argument("--min-app-version")
    issue_dev_parser.add_argument("--max-app-version")
    issue_dev_parser.add_argument("--private-key", type=Path)
    issue_dev_parser.add_argument("--output", required=True, type=Path)
    issue_dev_parser.add_argument("--history-file", type=Path, default=DEFAULT_HISTORY_FILE)
    issue_dev_parser.add_argument("--force", action="store_true")

    verify_parser = subparsers.add_parser("verify", help="verify an lflic-1 file")
    verify_parser.add_argument("--license", required=True, type=Path)
    verify_parser.add_argument("--public-key", required=True, type=Path)
    verify_parser.add_argument("--app-version")

    history_parser = subparsers.add_parser("history", help="show local masked issuing history")
    history_parser.add_argument("--history-file", type=Path, default=DEFAULT_HISTORY_FILE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            _print_request(_read_request(args))
            return 0

        if args.command in {"issue", "issue-dev"}:
            request_payload = _read_request(args)
            private_key_value = args.private_key or os.environ.get("LAUNCHFLOW_SIGNING_KEY")
            if not private_key_value:
                raise ValueError("必须通过 --private-key 或 LAUNCHFLOW_SIGNING_KEY 指定签名私钥路径")
            if args.command == "issue-dev":
                explicit_output = args.output.expanduser().resolve()
                output_dir = explicit_output.parent
                history_file = args.history_file.expanduser().resolve()
                edition = "developer"
                audit_action = "issue-dev"
            else:
                explicit_output = None
                output_dir = args.output_dir.expanduser().resolve()
                history_file = (args.history_file or output_dir / "license_admin_history.jsonl").expanduser().resolve()
                edition = args.edition
                audit_action = "issue"
            result = issue_license(
                request_payload,
                customer=args.customer,
                edition=edition,
                days=args.days,
                private_key_path=Path(private_key_value).expanduser().resolve(),
                output_dir=output_dir,
                history_file=history_file,
                output_path=explicit_output,
                features=args.feature,
                min_app_version=args.min_app_version,
                max_app_version=args.max_app_version,
                force=args.force,
                audit_action=audit_action,
            )
            print(f"license_id={result.license_data['license_id']}")
            print(f"request_id={result.license_data['request_id']}")
            print(f"output={result.output_path}")
            print(f"forced_duplicate={'true' if result.forced_duplicate else 'false'}")
            return 0

        if args.command == "verify":
            result = verify_license_file(args.license.resolve(), args.public_key.resolve(), app_version=args.app_version)
            license_data = result["license"]
            print(f"valid={'true' if result['valid'] else 'false'}")
            print(f"signature_valid={'true' if result['signature_valid'] else 'false'}")
            print(f"expired={'true' if result['expired'] else 'false'}")
            print(f"edition={license_data['edition']}")
            print(f"request_id={license_data['request_id']}")
            print(f"request_app_version={license_data['request_app_version']}")
            print(f"min_app_version={license_data['min_app_version']}")
            print(f"max_app_version={license_data['max_app_version']}")
            print(f"expires_at={license_data['expires_at']}")
            return 0 if result["valid"] else 1

        records = load_history(args.history_file.resolve())
        print(f"history_count={len(records)}")
        for record in records:
            print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
