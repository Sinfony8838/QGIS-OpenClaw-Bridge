from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


def _default_app_root() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "GeoBot"
    return Path.home() / "AppData" / "Roaming" / "GeoBot"


def _default_openclaw_home() -> Path:
    return Path.home() / ".openclaw"


def _detect_qgis_executable() -> str:
    candidates = []
    env_value = os.getenv("GEOBOT_QGIS_EXE", "").strip()
    if env_value:
        candidates.append(Path(env_value))

    candidates.extend(
        [
            Path(r"D:\QGIS 3.40.10\bin\qgis-ltr-bin.exe"),
            Path(r"D:\QGIS 3.40.10\bin\qgis-bin.exe"),
            Path(r"C:\Program Files\QGIS 3.40.10\bin\qgis-ltr-bin.exe"),
            Path(r"C:\Program Files\QGIS 3.40.10\bin\qgis-bin.exe"),
            Path(r"C:\Program Files\QGIS 3.34.0\bin\qgis-ltr-bin.exe"),
            Path(r"C:\Program Files\QGIS 3.34.0\bin\qgis-bin.exe"),
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def _as_bool(value: str, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_openclaw_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _detect_electron_executable(project_root: Path) -> str:
    env_value = os.getenv("GEOBOT_ELECTRON_EXE", "").strip()
    if env_value and Path(env_value).exists():
        return env_value

    candidates = [
        project_root / "geobot_desktop" / "node_modules" / "electron" / "dist" / "electron.exe",
        project_root / "geobot_desktop" / "node_modules" / ".bin" / "electron.cmd",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


@dataclass
class RuntimeConfig:
    host: str = "127.0.0.1"
    port: int = 18999
    qgis_host: str = "127.0.0.1"
    qgis_port: int = 5555
    app_root: Path = field(default_factory=_default_app_root)
    openclaw_home: Path = field(default_factory=_default_openclaw_home)
    openclaw_gateway_url: str = field(default_factory=lambda: os.getenv("GEOBOT_OPENCLAW_URL", "").strip())
    openclaw_gateway_token: str = field(default_factory=lambda: os.getenv("GEOBOT_OPENCLAW_TOKEN", "").strip())
    qgis_executable: str = field(default_factory=_detect_qgis_executable)
    assistant_engine: str = field(default_factory=lambda: os.getenv("GEOBOT_ASSISTANT_ENGINE", "openclaw").strip().lower() or "openclaw")
    assistant_fallback_templates: bool = field(default_factory=lambda: _as_bool(os.getenv("GEOBOT_ASSISTANT_FALLBACK_TEMPLATES", "1"), default=True))
    openclaw_bridge_mode: str = field(default_factory=lambda: os.getenv("GEOBOT_OPENCLAW_BRIDGE_MODE", "hidden-automation").strip().lower() or "hidden-automation")
    openclaw_bridge_timeout_ms: int = field(default_factory=lambda: int(os.getenv("GEOBOT_OPENCLAW_BRIDGE_TIMEOUT_MS", "420000")))
    desktop_automation_bridge_url: str = field(default_factory=lambda: os.getenv("GEOBOT_AUTOMATION_BRIDGE_URL", "http://127.0.0.1:19091").strip())
    population_showcase_mode: str = field(default_factory=lambda: os.getenv("GEOBOT_POPULATION_SHOWCASE_MODE", "population_unit").strip().lower() or "population_unit")
    population_knowledge_root: Optional[Path] = None
    population_dataset_manifest_path: Optional[Path] = None

    def __post_init__(self) -> None:
        self.project_root = Path(__file__).resolve().parents[1]
        self.runtime_dir = self.app_root / "runtime"
        self.workspace_dir = self.app_root / "workspace"
        self.outputs_dir = self.app_root / "outputs"
        self.logs_dir = self.app_root / "logs"
        self.openclaw_dir = self.runtime_dir / "openclaw"
        self.state_file = self.runtime_dir / "state.json"
        self.private_openclaw_token = self.openclaw_gateway_token or secrets.token_hex(24)

        self.openclaw_config_path = self.openclaw_home / "openclaw.json"
        self.openclaw_gateway_cmd = self.openclaw_home / "gateway.cmd"
        self.openclaw_workspace_dir = self.openclaw_home / "workspace"
        self.teacher_flow_skill_dir = self.openclaw_workspace_dir / "skills" / "teacher_flow"
        self.qgis_solver_skill_dir = self.openclaw_workspace_dir / "skills" / "qgis-solver"
        self.ppt_studio_skill_dir = self.openclaw_workspace_dir / "skills" / "ppt-studio"
        self.electron_executable = _detect_electron_executable(self.project_root)
        self.openclaw_helper_script = self.project_root / "geobot_runtime" / "openclaw_bridge_helper.js"
        if self.population_knowledge_root is None:
            env_root = os.getenv("GEOBOT_POPULATION_KNOWLEDGE_ROOT", "").strip()
            self.population_knowledge_root = Path(env_root) if env_root else self.openclaw_workspace_dir / "knowledge" / "geography" / "population"
        else:
            self.population_knowledge_root = Path(self.population_knowledge_root)
        if self.population_dataset_manifest_path is None:
            env_manifest = os.getenv("GEOBOT_POPULATION_MANIFEST_PATH", "").strip()
            self.population_dataset_manifest_path = Path(env_manifest) if env_manifest else self.runtime_dir / "population_dataset_manifest.json"
        else:
            self.population_dataset_manifest_path = Path(self.population_dataset_manifest_path)

        if not self.openclaw_gateway_url or not self.openclaw_gateway_token:
            self._hydrate_openclaw_settings_from_local_config()

    @property
    def runtime_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def openclaw_chat_url(self) -> str:
        return f"{self.openclaw_gateway_url.rstrip('/')}/chat" if self.openclaw_gateway_url else ""

    def ensure_dirs(self) -> None:
        for path in [self.app_root, self.runtime_dir, self.workspace_dir, self.outputs_dir, self.logs_dir, self.openclaw_dir]:
            path.mkdir(parents=True, exist_ok=True)
        self._write_runtime_manifest()
        self._write_private_openclaw_config()
        self._write_population_dataset_manifest()

    def project_output_dir(self, project_id: str) -> Path:
        path = self.outputs_dir / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _hydrate_openclaw_settings_from_local_config(self) -> None:
        payload = _read_openclaw_config(self.openclaw_config_path)
        gateway = payload.get("gateway", {})
        if not self.openclaw_gateway_url:
            port = gateway.get("port", 18789)
            bind = gateway.get("bind", "127.0.0.1")
            bind = "127.0.0.1" if bind in {"loopback", "localhost"} else bind
            self.openclaw_gateway_url = f"http://{bind}:{port}"
        if not self.openclaw_gateway_token:
            auth = gateway.get("auth", {})
            token = auth.get("token", "")
            if token:
                self.openclaw_gateway_token = token
        if self.openclaw_gateway_token:
            self.private_openclaw_token = self.openclaw_gateway_token

    def _write_runtime_manifest(self) -> None:
        manifest = {
            "product": "GeoBot",
            "runtime_api": self.runtime_url,
            "assistant_engine": self.assistant_engine,
            "assistant_fallback_templates": self.assistant_fallback_templates,
            "paths": {
                "runtime": str(self.runtime_dir),
                "workspace": str(self.workspace_dir),
                "outputs": str(self.outputs_dir),
                "logs": str(self.logs_dir),
            },
            "qgis_bridge": {
                "host": self.qgis_host,
                "port": self.qgis_port,
                "executable": self.qgis_executable,
            },
            "openclaw": {
                "home": str(self.openclaw_home),
                "workspace": str(self.openclaw_workspace_dir),
                "gateway_url": self.openclaw_gateway_url,
                "bridge_mode": self.openclaw_bridge_mode,
                "teacher_flow_skill": str(self.teacher_flow_skill_dir),
                "qgis_solver_skill": str(self.qgis_solver_skill_dir),
                "desktop_bridge_url": self.desktop_automation_bridge_url,
                "helper_script": str(self.openclaw_helper_script),
                "electron_executable": self.electron_executable,
            },
            "population_showcase": {
                "mode": self.population_showcase_mode,
                "knowledge_root": str(self.population_knowledge_root),
                "dataset_manifest_path": str(self.population_dataset_manifest_path),
            },
        }
        (self.runtime_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_private_openclaw_config(self) -> None:
        config = {
            "gateway": {
                "bind": "loopback",
                "mode": "local",
                "auth": {
                    "mode": "token",
                    "token": self.private_openclaw_token,
                },
            },
            "browser": {
                "enabled": False,
                "headless": True,
            },
            "product_wrapper": {
                "name": "GeoBot",
                "hidden_engine": "OpenClaw",
                "ui_exposed": False,
            },
        }
        (self.openclaw_dir / "openclaw.private.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_population_dataset_manifest(self) -> None:
        from .population_unit import build_population_dataset_manifest

        build_population_dataset_manifest(
            knowledge_root=self.population_knowledge_root,
            manifest_path=self.population_dataset_manifest_path,
            showcase_mode=self.population_showcase_mode,
        )
