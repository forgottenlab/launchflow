"""Smoke tests for missing-URL-scheme normalization."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from editor.ui.main_window import validate_plan_for_execution
from shared.basic_policy import validate_basic_plan_document
from shared.models import Plan, UrlStep
from shared.url_normalization import normalize_missing_url_scheme, normalize_plan_url_schemes
from tools.build_single_exe import _prepare_embedded_plan_and_assets, _serialized_url_open


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_normalize_function() -> None:
    require(normalize_missing_url_scheme("www.baidu.com") == "https://www.baidu.com", "bare domain was not prefixed")
    require(normalize_missing_url_scheme("  www.baidu.com  ") == "https://www.baidu.com", "stripped bare domain was not prefixed")
    require(normalize_missing_url_scheme("localhost:8080") == "https://localhost:8080", "host:port was not prefixed")
    require(normalize_missing_url_scheme("http://example.com") == "http://example.com", "explicit http was rewritten")
    require(normalize_missing_url_scheme("https://example.com/a") == "https://example.com/a", "explicit https was rewritten")
    require(normalize_missing_url_scheme("ftp://files.example.com") == "ftp://files.example.com", "explicit ftp was rewritten")
    require(normalize_missing_url_scheme("file:///C:/page.html") == "file:///C:/page.html", "explicit file was rewritten")
    require(normalize_missing_url_scheme("mailto:a@b.c") == "mailto:a@b.c", "explicit mailto was rewritten")
    require(normalize_missing_url_scheme("about:blank") == "about:blank", "explicit about was rewritten")
    require(normalize_missing_url_scheme("") == "", "empty URL was changed")
    require(normalize_missing_url_scheme("   ") == "", "whitespace-only URL was not stripped")


def check_plan_mutation() -> None:
    steps = [
        {"type": "url", "url": "www.baidu.com"},
        {"type": "url", "url": "https://kept.example"},
        {"type": "app", "path": "C:/App.exe"},
        UrlStep(name="web", url="localhost:8080"),
    ]
    require(normalize_plan_url_schemes(steps) is True, "expected at least one URL change")
    require(steps[0]["url"] == "https://www.baidu.com", "dict URL step was not normalized")
    require(steps[1]["url"] == "https://kept.example", "explicit https dict URL was rewritten")
    require(steps[2]["path"] == "C:/App.exe", "app step was mutated")
    require(steps[3].url == "https://localhost:8080", "UrlStep object was not normalized")


def check_basic_policy_accepts_bare_domain() -> None:
    result = validate_basic_plan_document(
        {
            "plan_name": "basic-url",
            "steps": [
                {"type": "url", "name": "新网页", "url": "www.baidu.com", "enabled": True, "delay_after": 1.0},
            ],
        }
    )
    require(result.accepted, "Basic rejected a bare http(s) host: %r" % (getattr(result, "issues", result),))
    issues = validate_basic_plan_document(
        {
            "plan_name": "basic-file",
            "steps": [
                {
                    "type": "url",
                    "name": "file",
                    "url": "file:///C:/LaunchFlow-Synthetic/page.html",
                    "enabled": True,
                    "delay_after": 1.0,
                },
            ],
        }
    )
    require(not issues.accepted, "Basic accepted an explicit file URL")
    require(
        any(issue.code == "basic_unsupported_url_scheme" for issue in issues.issues),
        "file URL did not report unsupported scheme",
    )


def check_validate_and_export() -> None:
    plan = Plan(plan_name="test", steps=[UrlStep(name="新网页", url="www.baidu.com")])
    issue = validate_plan_for_execution(plan, "试运行")
    require(issue is None, "trial-run validation rejected a bare domain: %s" % (issue,))
    require(plan.steps[0].url == "https://www.baidu.com", "validation did not persist the https prefix")

    prepared, assets = _prepare_embedded_plan_and_assets(
        {"plan_name": "test", "steps": [{"type": "url", "url": "www.baidu.com", "browser_path": ""}]}
    )
    require(assets == [], "URL export unexpectedly created an asset")
    require(prepared["steps"][0]["url"] == "https://www.baidu.com", "export plan URL was not normalized")
    require(
        prepared["steps"][0]["_url_open"]["url"] == "https://www.baidu.com",
        "serialized URL open contract was not normalized",
    )

    explicit = _serialized_url_open("http://example.com", "")
    require(explicit["url"] == "http://example.com", "explicit http was rewritten during serialize")


def main() -> int:
    check_normalize_function()
    check_plan_mutation()
    check_basic_policy_accepts_bare_domain()
    check_validate_and_export()
    print("url scheme normalization smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
