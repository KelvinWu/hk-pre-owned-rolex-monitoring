#!/usr/bin/env python3
"""在运行依赖安装前诊断并安装 HK Rolex Skill 的平台中立 Bootstrap。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import site
import subprocess
import sys
import sysconfig
import tempfile
import venv
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit


SKILL_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = SKILL_ROOT / "pyproject.toml"
VERSION_FILE = SKILL_ROOT / "src/inventory_sentinel/version.py"
MINIMUM_PYTHON = (3, 11)
Runner = Callable[..., subprocess.CompletedProcess[str]]


def read_version() -> str:
    try:
        text = VERSION_FILE.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return match.group(1) if match else "unknown"


def result_envelope(
    *,
    operation: str,
    status: str,
    ok: bool,
    state_modified: bool = False,
    result: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": ok,
        "operation": operation,
        "status": status,
        "skill_version": read_version(),
        "monitor_id": None,
        "run_id": None,
        "state_modified": state_modified,
        "result": result or {},
        "warnings": warnings or [],
        "error": error,
    }


def redact_url(value: str) -> str:
    """只保留镜像 origin，避免泄露用户名、密码、查询参数或路径 token。"""

    try:
        parsed = urlsplit(value.strip())
        port_value = parsed.port
    except ValueError:
        return "configured-redacted"
    if not parsed.scheme or not parsed.hostname:
        return "configured-redacted"
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{port_value}" if port_value else ""
    return f"{parsed.scheme}://{host}{port}"


def configured_index_urls(environment: Mapping[str, str]) -> list[str]:
    values: list[str] = []
    primary = environment.get("PIP_INDEX_URL", "").strip()
    if primary:
        values.append(primary)
    values.extend(environment.get("PIP_EXTRA_INDEX_URL", "").split())
    redacted: list[str] = []
    for value in values:
        safe = redact_url(value)
        if safe not in redacted:
            redacted.append(safe)
    return redacted


def read_dependencies() -> list[str]:
    if sys.version_info < MINIMUM_PYTHON:
        return []
    import tomllib

    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def default_runtime_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library/Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    return (base / "hk-pre-owned-rolex-monitoring/runtime/venv").expanduser().resolve()


def nearest_existing_path(path: Path) -> Path:
    current = path.expanduser().resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def path_is_writable(path: Path) -> bool:
    existing = nearest_existing_path(path)
    return existing.is_dir() and os.access(existing, os.W_OK | os.X_OK)


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(parent.expanduser().resolve())
        return True
    except ValueError:
        return False


def user_site_details(environment: Mapping[str, str]) -> dict[str, Any]:
    try:
        user_site = Path(site.getusersitepackages()).expanduser().resolve()
    except (AttributeError, TypeError):
        user_site = Path.home() / ".local/lib"
    try:
        scheme = "nt_user" if os.name == "nt" else "posix_user"
        user_scripts = Path(sysconfig.get_path("scripts", scheme=scheme)).expanduser().resolve()
    except (KeyError, TypeError):
        user_scripts = user_site.parent / ("Scripts" if os.name == "nt" else "bin")
    path_entries = {
        os.path.normcase(str(Path(entry).expanduser().resolve()))
        for entry in environment.get("PATH", "").split(os.pathsep)
        if entry
    }
    scripts_on_path = os.path.normcase(str(user_scripts)) in path_entries
    return {
        "enabled": bool(site.ENABLE_USER_SITE),
        "site_dir": str(user_site),
        "site_dir_writable": path_is_writable(user_site),
        "scripts_dir": str(user_scripts),
        "scripts_on_path": scripts_on_path,
    }


def choose_install_mode(
    requested: str,
    *,
    venv_available: bool,
    runtime_dir_writable: bool,
    user_site_enabled: bool,
    user_site_writable: bool,
) -> str | None:
    venv_ready = venv_available and runtime_dir_writable
    user_ready = user_site_enabled and user_site_writable
    if requested == "venv":
        return "venv" if venv_ready else None
    if requested == "user":
        return "user" if user_ready else None
    if venv_ready:
        return "venv"
    return "user" if user_ready else None


def inspect_installation(
    runtime_dir: Path,
    requested_mode: str,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    user = user_site_details(environment)
    venv_available = importlib.util.find_spec("venv") is not None
    runtime_writable = path_is_writable(runtime_dir)
    mode = choose_install_mode(
        requested_mode,
        venv_available=venv_available,
        runtime_dir_writable=runtime_writable,
        user_site_enabled=user["enabled"],
        user_site_writable=user["site_dir_writable"],
    )
    planned_python = runtime_python(runtime_dir) if mode == "venv" else Path(sys.executable)
    return {
        "requested_mode": requested_mode,
        "recommended_mode": mode,
        "runtime_dir": str(runtime_dir),
        "runtime_dir_writable": runtime_writable,
        "venv_available": venv_available,
        "user_site_enabled": user["enabled"],
        "user_site_dir": user["site_dir"],
        "user_site_writable": user["site_dir_writable"],
        "user_scripts_dir": user["scripts_dir"],
        "user_scripts_on_path": user["scripts_on_path"],
        "module_fallback": f"{planned_python} -m inventory_sentinel",
    }


def classify_pip_failure(stderr: str, *, configured_index: bool) -> str:
    lowered = stderr.lower()
    if any(marker in lowered for marker in ("name or service not known", "nodename nor servname", "temporary failure in name resolution")):
        return "INDEX_DNS_ERROR"
    if any(marker in lowered for marker in ("certificate verify failed", "sslerror", "tls")):
        return "INDEX_TLS_ERROR"
    timeout_markers = (
        "timed out",
        "timeout",
        "readtimeout",
        "connecttimeout",
        "max retries exceeded",
    )
    if any(marker in lowered for marker in timeout_markers):
        return "CONFIGURED_INDEX_DOWNLOAD_TIMEOUT" if configured_index else "DEFAULT_INDEX_DOWNLOAD_TIMEOUT"
    if "no matching distribution found" in lowered or "could not find a version that satisfies" in lowered:
        return "DEPENDENCY_NOT_AVAILABLE"
    if "permission denied" in lowered or "not writeable" in lowered or "not writable" in lowered:
        return "INSTALL_PERMISSION_DENIED"
    return "INDEX_DOWNLOAD_ERROR"


def probe_dependency_download(
    python_executable: str,
    dependencies: Sequence[str],
    *,
    environment: Mapping[str, str],
    timeout_seconds: int,
    runner: Runner = subprocess.run,
    download_dir: Path | None = None,
) -> dict[str, Any]:
    configured = bool(configured_index_urls(environment))
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if download_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="hk-rolex-bootstrap-")
        destination = Path(temporary.name)
    else:
        destination = download_dir
        destination.mkdir(parents=True, exist_ok=True)
    command = [
        python_executable,
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--dest",
        str(destination),
        *dependencies,
    ]
    process_environment = os.environ.copy()
    process_environment.update(environment)
    process_environment["PIP_DEFAULT_TIMEOUT"] = str(timeout_seconds)
    try:
        completed = runner(
            command,
            check=False,
            text=True,
            capture_output=True,
            env=process_environment,
            timeout=max(timeout_seconds * 8, 30),
        )
        if completed.returncode == 0:
            return {
                "status": "DEPENDENCIES_DOWNLOADABLE",
                "download_verified": True,
                "pip_exit_code": 0,
            }
        return {
            "status": classify_pip_failure(completed.stderr, configured_index=configured),
            "download_verified": False,
            "pip_exit_code": completed.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "CONFIGURED_INDEX_DOWNLOAD_TIMEOUT" if configured else "DEFAULT_INDEX_DOWNLOAD_TIMEOUT",
            "download_verified": False,
            "pip_exit_code": None,
        }
    finally:
        if temporary is not None:
            temporary.cleanup()


def network_result(
    mode: str,
    *,
    environment: Mapping[str, str],
    timeout_seconds: int,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    indexes = configured_index_urls(environment)
    base = {
        "check_mode": mode,
        "index_source": "environment" if indexes else "pip-default-or-config",
        "index_urls": indexes,
    }
    if mode == "skip":
        return {**base, "status": "NOT_RUN", "download_verified": False, "pip_exit_code": None}
    return {
        **base,
        **probe_dependency_download(
            sys.executable,
            read_dependencies(),
            environment=environment,
            timeout_seconds=timeout_seconds,
            runner=runner,
        ),
    }


def state_result(state_dir: str | None) -> dict[str, Any]:
    if not state_dir:
        return {
            "requested": False,
            "state_dir": None,
            "writable": None,
            "persistence": "host_verification_required",
        }
    path = Path(state_dir).expanduser().resolve()
    return {
        "requested": True,
        "state_dir": str(path),
        "writable": path_is_writable(path),
        "persistence": "host_verification_required",
    }


def doctor_payload(
    args: argparse.Namespace,
    *,
    environment: Mapping[str, str] | None = None,
    runner: Runner = subprocess.run,
) -> tuple[dict[str, Any], int]:
    environment = dict(os.environ if environment is None else environment)
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    python_supported = sys.version_info >= MINIMUM_PYTHON
    pip_available = importlib.util.find_spec("pip") is not None
    installation = inspect_installation(runtime_dir, args.install_mode, environment)
    state = state_result(args.state_dir)
    warnings: list[str] = []

    state_path = Path(args.state_dir).expanduser().resolve() if args.state_dir else None
    if path_is_within(runtime_dir, SKILL_ROOT):
        path_error = ("RUNTIME_DIR_INSIDE_SKILL", "运行虚拟环境不得位于 Skill 安装目录")
    elif state_path is not None and path_is_within(state_path, SKILL_ROOT):
        path_error = ("STATE_DIR_INSIDE_SKILL", "用户状态不得位于 Skill 安装目录")
    elif state_path is not None and (
        path_is_within(state_path, runtime_dir) or path_is_within(runtime_dir, state_path)
    ):
        path_error = ("RUNTIME_STATE_PATH_CONFLICT", "运行环境和用户状态目录不得相互嵌套")
    else:
        path_error = None

    if path_error is not None:
        network = {
            "check_mode": args.network_check,
            "index_source": "not_checked",
            "index_urls": [],
            "status": "NOT_RUN",
            "download_verified": False,
            "pip_exit_code": None,
        }
        status = "BLOCKED"
        error = {"code": path_error[0], "message": path_error[1]}
        next_action = "选择彼此独立且位于 Skill 安装目录之外的 runtime-dir 和 state-dir"
        exit_code = 3
    elif not python_supported:
        network = {
            "check_mode": args.network_check,
            "index_source": "not_checked",
            "index_urls": [],
            "status": "NOT_RUN",
            "download_verified": False,
            "pip_exit_code": None,
        }
        status = "BLOCKED"
        error = {"code": "UNSUPPORTED_PYTHON", "message": "需要 Python 3.11 或更高版本"}
        next_action = "更换到 Python 3.11+ 后重新运行 bootstrap doctor"
        exit_code = 3
    elif not pip_available:
        network = {
            "check_mode": args.network_check,
            "index_source": "not_checked",
            "index_urls": [],
            "status": "NOT_RUN",
            "download_verified": False,
            "pip_exit_code": None,
        }
        status = "BLOCKED"
        error = {"code": "PIP_UNAVAILABLE", "message": "当前 Python 没有可调用的 pip"}
        next_action = "为当前 Python 启用 pip 后重新运行 bootstrap doctor"
        exit_code = 3
    else:
        network = network_result(
            args.network_check,
            environment=environment,
            timeout_seconds=args.timeout,
            runner=runner,
        )
        if installation["recommended_mode"] is None:
            status = "BLOCKED"
            error = {"code": "NO_WRITABLE_INSTALL_TARGET", "message": "没有可写的虚拟环境或用户安装目录"}
            next_action = "向宿主提供可写的 --runtime-dir，或启用可写的 Python user site"
            exit_code = 4
        elif state["requested"] and not state["writable"]:
            status = "BLOCKED"
            error = {"code": "STATE_DIR_NOT_WRITABLE", "message": "指定的状态目录不可写"}
            next_action = "改用宿主可持久且可写的 --state-dir"
            exit_code = 4
        elif args.network_check == "download" and not network["download_verified"]:
            status = "BLOCKED"
            code = str(network["status"])
            error = {"code": code, "message": "依赖包实际下载检查失败"}
            next_action = (
                "检查网络，或由用户/宿主配置可信的 PIP_INDEX_URL 后重新运行 bootstrap doctor"
            )
            exit_code = 4
        elif args.network_check == "skip":
            status = "READY_WITH_UNVERIFIED_NETWORK"
            error = None
            next_action = "安装前运行 download 检查，或在已确认依赖可用时执行 bootstrap install"
            warnings.append("未执行依赖包下载检查；不能据此声称安装网络已经验证")
            exit_code = 0
        else:
            status = "READY"
            error = None
            next_action = "执行 bootstrap install，并检查结构化安装回执"
            exit_code = 0

    if installation["recommended_mode"] == "user" and not installation["user_scripts_on_path"]:
        warnings.append("用户级 Scripts 目录不在 PATH；安装后使用 Python 模块入口或绝对路径")

    payload = result_envelope(
        operation="bootstrap.doctor",
        status=status,
        ok=error is None,
        result={
            "python": {
                "executable": sys.executable,
                "version": platform.python_version(),
                "minimum_version": "3.11",
                "supported": python_supported,
                "platform": sys.platform,
                "machine": platform.machine(),
                "virtual_environment": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
            },
            "pip": {"available": pip_available},
            "network": network,
            "installation": installation,
            "state": state,
            "next_action": next_action,
        },
        warnings=warnings,
        error=error,
    )
    return payload, exit_code


def build_install_command(python_executable: str, package: str, mode: str) -> list[str]:
    command = [python_executable, "-m", "pip", "install", "--disable-pip-version-check"]
    if mode == "user":
        command.append("--user")
    command.append(package)
    return command


def runtime_python(runtime_dir: Path) -> Path:
    if os.name == "nt":
        return runtime_dir / "Scripts/python.exe"
    return runtime_dir / "bin/python"


def runtime_inventoryctl(runtime_dir: Path) -> Path:
    if os.name == "nt":
        return runtime_dir / "Scripts/inventoryctl.exe"
    return runtime_dir / "bin/inventoryctl"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_completed_process(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    timeout_seconds: int,
    runner: Runner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    process_environment.update(environment)
    process_environment["PIP_DEFAULT_TIMEOUT"] = str(timeout_seconds)
    return runner(
        list(command),
        check=False,
        text=True,
        capture_output=True,
        env=process_environment,
        timeout=max(timeout_seconds * 12, 60),
    )


def install_payload(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    environment = dict(os.environ)
    package = Path(args.package).expanduser().resolve()
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    if not package.exists():
        return (
            result_envelope(
                operation="bootstrap.install",
                status="INSTALL_BLOCKED",
                ok=False,
                error={"code": "PACKAGE_NOT_FOUND", "message": "指定的本地安装包不存在"},
            ),
            3,
        )

    if args.sha256:
        actual_sha256 = sha256_file(package) if package.is_file() else None
        if actual_sha256 != args.sha256.lower():
            return (
                result_envelope(
                    operation="bootstrap.install",
                    status="INSTALL_BLOCKED",
                    ok=False,
                    error={"code": "PACKAGE_CHECKSUM_MISMATCH", "message": "安装包 SHA-256 校验失败"},
                ),
                3,
            )
    else:
        actual_sha256 = sha256_file(package) if package.is_file() else None

    doctor, doctor_exit = doctor_payload(args, environment=environment)
    installation = dict(doctor["result"]["installation"])
    mode = installation["recommended_mode"]
    plan_result = {
        "package": {
            "path": str(package),
            "kind": "wheel" if package.suffix == ".whl" else "source",
            "sha256": actual_sha256,
            "checksum_required": bool(args.sha256),
            "checksum_verified": bool(args.sha256),
        },
        "network": doctor["result"]["network"],
        "installation": {**installation, "mode": mode},
        "verification": {"performed": False},
    }
    if doctor_exit != 0:
        return (
            result_envelope(
                operation="bootstrap.install",
                status="INSTALL_BLOCKED",
                ok=False,
                result=plan_result,
                warnings=doctor["warnings"],
                error=doctor["error"],
            ),
            doctor_exit,
        )
    if args.dry_run:
        return (
            result_envelope(
                operation="bootstrap.install",
                status="INSTALL_PLANNED",
                ok=True,
                result=plan_result,
                warnings=doctor["warnings"],
            ),
            0,
        )

    warnings = list(doctor["warnings"])
    state_modified = False
    selected_python = Path(sys.executable)
    if mode == "venv":
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(runtime_dir)
            state_modified = True
            selected_python = runtime_python(runtime_dir)
        except (OSError, subprocess.SubprocessError):
            fallback = choose_install_mode(
                "user",
                venv_available=False,
                runtime_dir_writable=False,
                user_site_enabled=installation["user_site_enabled"],
                user_site_writable=installation["user_site_writable"],
            )
            if args.install_mode == "auto" and fallback == "user":
                mode = "user"
                selected_python = Path(sys.executable)
                warnings.append("虚拟环境创建失败，已回退到可写的用户级安装目录")
            else:
                return (
                    result_envelope(
                        operation="bootstrap.install",
                        status="INSTALL_FAILED",
                        ok=False,
                        state_modified=state_modified,
                        result=plan_result,
                        warnings=warnings,
                        error={"code": "VENV_CREATE_FAILED", "message": "无法创建运行虚拟环境"},
                    ),
                    4,
                )

    command = build_install_command(str(selected_python), str(package), mode)
    try:
        completed = safe_completed_process(
            command,
            environment=environment,
            timeout_seconds=args.timeout,
        )
    except subprocess.TimeoutExpired:
        completed = subprocess.CompletedProcess(command, 1, stdout="", stderr="download timed out")
    if completed.returncode != 0:
        code = classify_pip_failure(
            completed.stderr,
            configured_index=bool(configured_index_urls(environment)),
        )
        return (
            result_envelope(
                operation="bootstrap.install",
                status="INSTALL_FAILED",
                ok=False,
                state_modified=state_modified or mode == "user",
                result=plan_result,
                warnings=warnings,
                error={"code": code, "message": "Python 运行依赖安装失败"},
            ),
            4,
        )

    state_modified = True
    verify_command = [str(selected_python), "-m", "inventory_sentinel", "skill", "info", "--json"]
    verification = safe_completed_process(
        verify_command,
        environment=environment,
        timeout_seconds=args.timeout,
    )
    try:
        verified_payload = json.loads(verification.stdout)
    except json.JSONDecodeError:
        verified_payload = None
    if verification.returncode != 0 or not isinstance(verified_payload, dict) or not verified_payload.get("ok"):
        return (
            result_envelope(
                operation="bootstrap.install",
                status="INSTALL_UNVERIFIED",
                ok=False,
                state_modified=state_modified,
                result=plan_result,
                warnings=warnings,
                error={"code": "SKILL_INFO_VERIFICATION_FAILED", "message": "安装后 skill info 验证失败"},
            ),
            4,
        )

    runtime_probe: dict[str, Any] | None = None
    if args.state_dir:
        probe_command = [
            str(selected_python),
            "-m",
            "inventory_sentinel",
            "--state-dir",
            str(Path(args.state_dir).expanduser().resolve()),
            "runtime",
            "probe",
            "--json",
        ]
        probe = safe_completed_process(
            probe_command,
            environment=environment,
            timeout_seconds=args.timeout,
        )
        try:
            runtime_probe = json.loads(probe.stdout)
        except json.JSONDecodeError:
            runtime_probe = None
        if probe.returncode != 0 or not isinstance(runtime_probe, dict) or not runtime_probe.get("ok"):
            return (
                result_envelope(
                    operation="bootstrap.install",
                    status="INSTALL_UNVERIFIED",
                    ok=False,
                    state_modified=True,
                    result=plan_result,
                    warnings=warnings,
                    error={"code": "RUNTIME_PROBE_VERIFICATION_FAILED", "message": "安装后 runtime probe 验证失败"},
                ),
                4,
            )

    inventoryctl_path = runtime_inventoryctl(runtime_dir) if mode == "venv" else Path(installation["user_scripts_dir"]) / ("inventoryctl.exe" if os.name == "nt" else "inventoryctl")
    module_command = f"{selected_python} -m inventory_sentinel"
    plan_result["installation"] = {
        **installation,
        "mode": mode,
        "python_executable": str(selected_python),
        "inventoryctl_path": str(inventoryctl_path) if inventoryctl_path.exists() else None,
        "module_fallback": module_command,
    }
    plan_result["verification"] = {
        "performed": True,
        "skill_info_ok": True,
        "installed_name": verified_payload["result"].get("name"),
        "installed_version": verified_payload["result"].get("version"),
        "runtime_probe_performed": runtime_probe is not None,
        "runtime_probe_ok": runtime_probe.get("ok") if runtime_probe else None,
    }
    if mode == "user" and not installation["user_scripts_on_path"]:
        warnings.append("inventoryctl 可能不在 PATH；请使用返回的 Python 模块入口")
    return (
        result_envelope(
            operation="bootstrap.install",
            status="INSTALL_VERIFIED",
            ok=True,
            state_modified=True,
            result=plan_result,
            warnings=warnings,
        ),
        0,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="诊断并安装 HK Pre-owned Rolex Monitoring 运行环境")
    subcommands = parser.add_subparsers(dest="operation", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--runtime-dir", default=str(default_runtime_dir()))
        target.add_argument("--state-dir")
        target.add_argument("--install-mode", choices=("auto", "venv", "user"), default="auto")
        target.add_argument("--network-check", choices=("download", "skip"), default="download")
        target.add_argument("--timeout", type=int, default=15)
        target.add_argument("--json", action="store_true", help="输出结构化 JSON（默认行为）")

    doctor = subcommands.add_parser("doctor")
    add_common(doctor)

    install = subcommands.add_parser("install")
    add_common(install)
    install.set_defaults(network_check="skip")
    install.add_argument("--package", default=str(SKILL_ROOT), help="本地 wheel 或 Skill 源码目录")
    install.add_argument("--sha256", help="本地 wheel 的预期 SHA-256")
    install.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout < 1:
        payload = result_envelope(
            operation=f"bootstrap.{args.operation}",
            status="ERROR",
            ok=False,
            error={"code": "INVALID_TIMEOUT", "message": "--timeout 必须大于 0"},
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 3
    try:
        if args.operation == "doctor":
            payload, exit_code = doctor_payload(args)
        else:
            payload, exit_code = install_payload(args)
    except Exception:
        payload = result_envelope(
            operation=f"bootstrap.{args.operation}",
            status="ERROR",
            ok=False,
            error={"code": "BOOTSTRAP_UNEXPECTED_ERROR", "message": "Bootstrap 发生未预期错误"},
        )
        exit_code = 4
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
