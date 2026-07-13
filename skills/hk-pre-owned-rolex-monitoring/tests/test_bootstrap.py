from __future__ import annotations

import importlib.util
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = SKILL_ROOT / "scripts/bootstrap.py"


def load_bootstrap_module():
    spec = importlib.util.spec_from_file_location("inventory_bootstrap", BOOTSTRAP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke_bootstrap(*args: str, env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], dict]:
    environment = os.environ.copy()
    if env:
        environment.update(env)
    completed = subprocess.run(
        [sys.executable, str(BOOTSTRAP), *args],
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )
    return completed, json.loads(completed.stdout)


def test_doctor_runs_before_dependencies_and_redacts_configured_index(tmp_path: Path) -> None:
    process, payload = invoke_bootstrap(
        "doctor",
        "--network-check",
        "skip",
        "--runtime-dir",
        str(tmp_path / "runtime"),
        "--json",
        env={
            "PIP_INDEX_URL": "https://mirror-user:mirror-secret@example.invalid/simple?token=hidden",
            "PIP_EXTRA_INDEX_URL": "",
            "PATH": "",
        },
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert process.returncode == 0
    assert payload["operation"] == "bootstrap.doctor"
    assert payload["status"] == "READY_WITH_UNVERIFIED_NETWORK"
    assert payload["state_modified"] is False
    assert payload["result"]["network"]["index_source"] == "environment"
    assert payload["result"]["network"]["index_urls"] == ["https://example.invalid"]
    assert payload["result"]["installation"]["user_scripts_on_path"] is False
    assert payload["result"]["installation"]["module_fallback"].endswith(
        " -m inventory_sentinel"
    )
    assert "mirror-user" not in serialized
    assert "mirror-secret" not in serialized
    assert "token" not in serialized


def test_malformed_index_url_still_returns_structured_redacted_json(tmp_path: Path) -> None:
    process, payload = invoke_bootstrap(
        "doctor",
        "--network-check",
        "skip",
        "--runtime-dir",
        str(tmp_path / "runtime"),
        "--json",
        env={
            "PIP_INDEX_URL": "https://mirror-user:mirror-secret@example.invalid:notaport/simple?token=hidden",
            "PIP_EXTRA_INDEX_URL": "",
        },
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert process.returncode == 0
    assert payload["result"]["network"]["index_urls"] == ["configured-redacted"]
    assert "mirror-user" not in serialized
    assert "mirror-secret" not in serialized
    assert "token" not in serialized


def test_network_probe_classifies_default_and_configured_index_timeouts(tmp_path: Path) -> None:
    module = load_bootstrap_module()

    def timeout_runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="HTTPSConnectionPool: Read timed out while downloading wheel",
        )

    default = module.probe_dependency_download(
        sys.executable,
        ["httpx>=0.27,<1"],
        environment={},
        timeout_seconds=5,
        runner=timeout_runner,
        download_dir=tmp_path / "default",
    )
    configured = module.probe_dependency_download(
        sys.executable,
        ["httpx>=0.27,<1"],
        environment={"PIP_INDEX_URL": "https://mirror.example/simple"},
        timeout_seconds=5,
        runner=timeout_runner,
        download_dir=tmp_path / "configured",
    )

    assert default["status"] == "DEFAULT_INDEX_DOWNLOAD_TIMEOUT"
    assert configured["status"] == "CONFIGURED_INDEX_DOWNLOAD_TIMEOUT"
    assert default["download_verified"] is False
    assert configured["download_verified"] is False


def test_dns_failure_is_not_mislabeled_as_a_generic_timeout() -> None:
    module = load_bootstrap_module()

    assert module.classify_pip_failure(
        "Max retries exceeded after NewConnectionError: nodename nor servname provided",
        configured_index=False,
    ) == "INDEX_DNS_ERROR"


def test_doctor_checks_download_by_default_but_install_does_not_download_twice() -> None:
    module = load_bootstrap_module()
    parser = module.build_parser()

    assert parser.parse_args(["doctor"]).network_check == "download"
    assert parser.parse_args(["install"]).network_check == "skip"


def test_install_mode_is_venv_first_then_user_site() -> None:
    module = load_bootstrap_module()

    assert module.choose_install_mode(
        "auto",
        venv_available=True,
        runtime_dir_writable=True,
        user_site_enabled=True,
        user_site_writable=True,
    ) == "venv"
    assert module.choose_install_mode(
        "auto",
        venv_available=False,
        runtime_dir_writable=False,
        user_site_enabled=True,
        user_site_writable=True,
    ) == "user"
    assert module.choose_install_mode(
        "auto",
        venv_available=False,
        runtime_dir_writable=False,
        user_site_enabled=False,
        user_site_writable=False,
    ) is None


def test_install_commands_never_use_sudo_or_editable_mode() -> None:
    module = load_bootstrap_module()

    venv_command = module.build_install_command(
        "/runtime/bin/python",
        "/release/hk_pre_owned_rolex_monitoring-0.1.1-py3-none-any.whl",
        "venv",
    )
    user_command = module.build_install_command(
        sys.executable,
        "/release/hk_pre_owned_rolex_monitoring-0.1.1-py3-none-any.whl",
        "user",
    )

    assert venv_command[:4] == ["/runtime/bin/python", "-m", "pip", "install"]
    assert "--user" not in venv_command
    assert "--user" in user_command
    assert "sudo" not in venv_command + user_command
    assert "-e" not in venv_command + user_command


def test_install_dry_run_returns_auditable_plan_without_writing(tmp_path: Path) -> None:
    package = tmp_path / "skill.whl"
    package.write_bytes(b"fixture")
    process, payload = invoke_bootstrap(
        "install",
        "--package",
        str(package),
        "--runtime-dir",
        str(tmp_path / "runtime"),
        "--network-check",
        "skip",
        "--dry-run",
        "--json",
    )

    assert process.returncode == 0
    assert payload["status"] == "INSTALL_PLANNED"
    assert payload["state_modified"] is False
    assert payload["result"]["installation"]["mode"] == "venv"
    assert payload["result"]["verification"]["performed"] is False
    assert not (tmp_path / "runtime").exists()


def test_auto_install_falls_back_to_user_site_after_venv_permission_error(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_bootstrap_module()
    package = tmp_path / "skill.whl"
    package.write_bytes(b"fixture")
    calls: list[list[str]] = []

    doctor = module.result_envelope(
        operation="bootstrap.doctor",
        status="READY_WITH_UNVERIFIED_NETWORK",
        ok=True,
        result={
            "network": {"status": "NOT_RUN", "download_verified": False},
            "installation": {
                "requested_mode": "auto",
                "recommended_mode": "venv",
                "runtime_dir": str(tmp_path / "runtime"),
                "runtime_dir_writable": True,
                "venv_available": True,
                "user_site_enabled": True,
                "user_site_dir": str(tmp_path / "user-site"),
                "user_site_writable": True,
                "user_scripts_dir": str(tmp_path / "user-bin"),
                "user_scripts_on_path": False,
                "module_fallback": f"{sys.executable} -m inventory_sentinel",
            },
        },
    )

    def deny_venv(self, path):
        raise PermissionError("fixture permission denied")

    def fake_process(command, **kwargs):
        calls.append(list(command))
        if "pip" in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "result": {
                        "name": "hk-pre-owned-rolex-monitoring",
                        "version": "0.1.1",
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(module, "doctor_payload", lambda *args, **kwargs: (doctor, 0))
    monkeypatch.setattr(module.venv.EnvBuilder, "create", deny_venv)
    monkeypatch.setattr(module, "safe_completed_process", fake_process)
    args = argparse.Namespace(
        package=str(package),
        runtime_dir=str(tmp_path / "runtime"),
        state_dir=None,
        install_mode="auto",
        network_check="skip",
        timeout=5,
        sha256=None,
        dry_run=False,
    )

    payload, exit_code = module.install_payload(args)

    assert exit_code == 0
    assert payload["status"] == "INSTALL_VERIFIED"
    assert payload["result"]["installation"]["mode"] == "user"
    assert "--user" in calls[0]
    assert any("回退" in warning for warning in payload["warnings"])


def test_checksum_mismatch_stops_before_runtime_is_modified(tmp_path: Path) -> None:
    package = tmp_path / "skill.whl"
    package.write_bytes(b"fixture")
    process, payload = invoke_bootstrap(
        "install",
        "--package",
        str(package),
        "--sha256",
        "0" * 64,
        "--runtime-dir",
        str(tmp_path / "runtime"),
        "--network-check",
        "skip",
        "--json",
    )

    assert process.returncode == 3
    assert payload["error"]["code"] == "PACKAGE_CHECKSUM_MISMATCH"
    assert payload["state_modified"] is False
    assert not (tmp_path / "runtime").exists()


def test_doctor_blocks_runtime_or_state_inside_skill_directory(tmp_path: Path) -> None:
    runtime_process, runtime_payload = invoke_bootstrap(
        "doctor",
        "--network-check",
        "skip",
        "--runtime-dir",
        str(SKILL_ROOT / ".runtime-fixture"),
        "--state-dir",
        str(tmp_path / "state"),
        "--json",
    )
    state_process, state_payload = invoke_bootstrap(
        "doctor",
        "--network-check",
        "skip",
        "--runtime-dir",
        str(tmp_path / "runtime"),
        "--state-dir",
        str(SKILL_ROOT / ".state-fixture"),
        "--json",
    )

    assert runtime_process.returncode == 3
    assert runtime_payload["error"]["code"] == "RUNTIME_DIR_INSIDE_SKILL"
    assert state_process.returncode == 3
    assert state_payload["error"]["code"] == "STATE_DIR_INSIDE_SKILL"


def test_doctor_blocks_nested_runtime_and_state_directories(tmp_path: Path) -> None:
    process, payload = invoke_bootstrap(
        "doctor",
        "--network-check",
        "skip",
        "--runtime-dir",
        str(tmp_path / "runtime"),
        "--state-dir",
        str(tmp_path / "runtime/state"),
        "--json",
    )

    assert process.returncode == 3
    assert payload["error"]["code"] == "RUNTIME_STATE_PATH_CONFLICT"


def test_bootstrap_contains_no_hardcoded_mirror_or_host_specific_logic() -> None:
    text = BOOTSTRAP.read_text(encoding="utf-8").lower()

    assert "mirrors.aliyun" not in text
    assert "pypi.tuna" not in text
    assert "sudo" not in text
    assert ("qc" + "law") not in text


def test_skill_routes_installation_through_bootstrap_before_inventory_cli() -> None:
    skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    bootstrap_position = skill_text.index("bootstrap.py doctor")
    inventory_position = skill_text.index("inventoryctl.py skill info")

    assert bootstrap_position < inventory_position
    assert "PIP_INDEX_URL" in skill_text
