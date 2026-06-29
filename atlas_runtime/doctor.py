"""Installation and runtime health checks for atlas-skill."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from finding import store

from .config import add_config_argument, config_value, load_atlas_config
from .models import is_anthropic_model, is_bedrock_model, resolve_model_profile
from .traces import DEFAULT_TRACE_ROOT

OK = "ok"
WARN = "warn"
ERROR = "error"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str


def run_checks(
    *,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
    trace_root: Path | str = DEFAULT_TRACE_ROOT,
    trace_output: Path | str | None = None,
    atlas_model: str | None = None,
    claude_code: bool = False,
    codex: bool = False,
    dashboard_port: int | None = None,
) -> list[DoctorCheck]:
    """Return a readably ordered list of health checks.

    Path checks create and remove one temporary file in each directory. They do
    not create a program manifest or modify taxonomy/trace records.
    """
    checks: list[DoctorCheck] = []
    checks.append(_python_check())
    checks.append(_import_check("openai"))
    checks.append(_writable_dir_check("taxonomy store", Path(store_dir)))
    checks.append(_writable_dir_check("trace root", Path(trace_root)))
    if trace_output is not None:
        checks.append(_writable_dir_check("trace output", Path(trace_output)))
    if atlas_model:
        checks.extend(_model_checks(atlas_model))
    else:
        checks.append(DoctorCheck(
            "atlas model",
            WARN,
            "no --atlas-model supplied; skipping model/profile/credential checks",
        ))
    if claude_code:
        checks.append(_claude_code_check())
    if codex:
        checks.extend(_codex_checks())
    if dashboard_port is not None:
        checks.append(_dashboard_port_check(dashboard_port))
    return checks


def has_errors(checks: Iterable[DoctorCheck]) -> bool:
    return any(check.status == ERROR for check in checks)


def _python_check() -> DoctorCheck:
    version = sys.version_info
    if version >= (3, 10):
        return DoctorCheck(
            "python",
            OK,
            f"{version.major}.{version.minor}.{version.micro} satisfies >=3.10",
        )
    return DoctorCheck(
        "python",
        ERROR,
        f"{version.major}.{version.minor}.{version.micro} is too old; need >=3.10",
    )


def _import_check(module: str) -> DoctorCheck:
    try:
        __import__(module)
    except Exception as exc:  # noqa: BLE001
        return DoctorCheck(
            f"import:{module}",
            ERROR,
            f"could not import {module}: {exc}",
        )
    return DoctorCheck(f"import:{module}", OK, f"{module} import works")


def _writable_dir_check(name: str, path: Path) -> DoctorCheck:
    try:
        path = path.expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".atlas-doctor-",
            suffix=".tmp",
            dir=path,
            delete=False,
        ) as fh:
            fh.write(b"atlas doctor\n")
            temporary = Path(fh.name)
        temporary.unlink()
    except Exception as exc:  # noqa: BLE001
        return DoctorCheck(name, ERROR, f"{path} is not writable: {exc}")
    return DoctorCheck(name, OK, f"{path} is writable")


def _model_checks(model: str) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    try:
        profile = resolve_model_profile(model)
    except ValueError as exc:
        return [DoctorCheck("atlas model", ERROR, str(exc))]
    checks.append(DoctorCheck(
        "atlas model",
        OK,
        (
            f"{model!r} recognized "
            f"({profile.context_tokens} context tokens)"
        ),
    ))
    checks.append(_credential_check(model))
    return checks


def _credential_check(model: str) -> DoctorCheck:
    if is_anthropic_model(model) and not os.environ.get("OPENAI_BASE_URL"):
        if is_bedrock_model(model):
            if os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
                try:
                    __import__("boto3")
                except Exception as exc:  # noqa: BLE001
                    return DoctorCheck(
                        "model credentials",
                        WARN,
                        (
                            "AWS_BEARER_TOKEN_BEDROCK is present, but boto3 "
                            f"could not be imported: {exc}"
                        ),
                    )
                return DoctorCheck(
                    "model credentials",
                    OK,
                    "Bedrock bearer-token environment is present and boto3 imports",
                )
            candidates = (
                "AWS_PROFILE",
                "AWS_ACCESS_KEY_ID",
            )
            if any(os.environ.get(name) for name in candidates):
                return DoctorCheck(
                    "model credentials",
                    OK,
                    "Bedrock/AWS credential environment is present",
                )
            return DoctorCheck(
                "model credentials",
                WARN,
                "no obvious Bedrock/AWS credential env found",
            )
        if os.environ.get("ANTHROPIC_API_KEY"):
            return DoctorCheck(
                "model credentials",
                OK,
                "ANTHROPIC_API_KEY is present",
            )
        return DoctorCheck(
            "model credentials",
            WARN,
            "ANTHROPIC_API_KEY is not set",
        )
    if model.lower().startswith("gemini"):
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            return DoctorCheck(
                "model credentials",
                OK,
                "Gemini credential environment is present",
            )
        return DoctorCheck(
            "model credentials",
            WARN,
            "GEMINI_API_KEY/GOOGLE_API_KEY is not set",
        )
    if os.environ.get("OPENAI_API_KEY"):
        return DoctorCheck("model credentials", OK, "OPENAI_API_KEY is present")
    if os.environ.get("OPENAI_BASE_URL"):
        return DoctorCheck(
            "model credentials",
            WARN,
            "OPENAI_BASE_URL is set but OPENAI_API_KEY is not; local endpoints may still work",
        )
    return DoctorCheck("model credentials", WARN, "OPENAI_API_KEY is not set")


def _claude_code_check() -> DoctorCheck:
    try:
        from atlas_integration.claude_code.install import verify_installed_hooks

        version = verify_installed_hooks()
    except Exception as exc:  # noqa: BLE001
        return DoctorCheck("claude code", ERROR, str(exc))
    return DoctorCheck("claude code", OK, f"hook contract verified: {version}")


def _codex_checks() -> list[DoctorCheck]:
    return [_codex_cli_check(), _codex_hooks_feature_check()]


def _codex_cli_check() -> DoctorCheck:
    executable = shutil.which("codex")
    if not executable:
        return DoctorCheck(
            "codex cli",
            WARN,
            "codex executable was not found on PATH; app-managed Codex may still work",
        )
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return DoctorCheck(
            "codex cli",
            WARN,
            f"found {executable}, but could not run --version: {exc}",
        )
    version = (result.stdout or result.stderr).strip()
    if result.returncode == 0:
        return DoctorCheck(
            "codex cli",
            OK,
            f"found {executable}: {version or 'version command succeeded'}",
        )
    return DoctorCheck(
        "codex cli",
        WARN,
        f"found {executable}, but --version exited {result.returncode}: {version}",
    )


def _codex_hooks_feature_check() -> DoctorCheck:
    disabled_locations = []
    for path in (
        Path.home() / ".codex" / "config.toml",
        Path.cwd() / ".codex" / "config.toml",
    ):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except OSError:
            continue
        compact = "".join(text.split())
        if "[features]" in compact and (
            "hooks=false" in compact or "codex_hooks=false" in compact
        ):
            disabled_locations.append(str(path))
    if disabled_locations:
        return DoctorCheck(
            "codex hooks",
            WARN,
            "hooks appear disabled in " + ", ".join(disabled_locations),
        )
    return DoctorCheck(
        "codex hooks",
        OK,
        "no local config disabling Codex hooks was found; review/trust with /hooks after install",
    )


def _dashboard_port_check(port: int) -> DoctorCheck:
    if port < 0 or port > 65_535:
        return DoctorCheck("dashboard port", ERROR, f"invalid port: {port}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        return DoctorCheck(
            "dashboard port",
            WARN,
            f"127.0.0.1:{port} is not currently bindable: {exc}",
        )
    finally:
        sock.close()
    label = "an ephemeral localhost port" if port == 0 else f"127.0.0.1:{port}"
    return DoctorCheck("dashboard port", OK, f"{label} is available")


def _render_text(checks: list[DoctorCheck]) -> str:
    width = max(len(check.name) for check in checks) if checks else 0
    lines = ["ATLAS doctor"]
    for check in checks:
        lines.append(
            f"[{check.status.upper():5}] {check.name:<{width}}  {check.message}"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check atlas-skill installation, storage, model, and optional integrations."
    )
    add_config_argument(parser)
    parser.add_argument("--store-dir")
    parser.add_argument("--trace-root")
    parser.add_argument("--trace-output")
    parser.add_argument("--atlas-model")
    parser.add_argument(
        "--claude-code",
        action="store_true",
        help="also verify the installed Claude Code hook contract",
    )
    parser.add_argument(
        "--codex",
        action="store_true",
        help="also check Codex CLI/hook availability",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        help="check whether a dashboard port is currently bindable",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    try:
        config = load_atlas_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    checks = run_checks(
        store_dir=config_value(args, config, "store_dir", store.DEFAULT_STORE_DIR),
        trace_root=config_value(args, config, "trace_root", DEFAULT_TRACE_ROOT),
        trace_output=config_value(args, config, "trace_output"),
        atlas_model=config_value(args, config, "atlas_model"),
        claude_code=args.claude_code,
        codex=args.codex,
        dashboard_port=args.dashboard_port,
    )
    if args.json:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        print(_render_text(checks))
    return 1 if has_errors(checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
