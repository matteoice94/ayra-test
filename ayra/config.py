"""Caricamento configurazione: config.yaml + override da variabili d'ambiente."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
EXAMPLE_PATH = ROOT / "config.example.yaml"


class LLMConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5:3b"
    api_key: str = ""
    supports_tools: bool = True
    timeout: float = 120.0


class ServerConfig(BaseModel):
    port: int = 8765


class AgentConfig(BaseModel):
    max_steps: int = 6
    history_messages: int = 20
    system_prompt: str = (
        "Sei Ayra, un assistente locale conciso e utile su Windows. "
        "Rispondi nella lingua dell'utente, in modo breve e concreto."
    )


class LaunchConfig(BaseModel):
    allowlist: list[str] = Field(default_factory=list)


class PerceptionConfig(BaseModel):
    self_title: str = "Ayra"
    max_nodes: int = 150
    max_depth: int = 8
    max_chars: int = 4000
    uia_timeout: float = 3.0
    ocr_min_chars: int = 40
    blocklist_processes: list[str] = Field(
        default_factory=lambda: ["keepass.exe", "keepassxc.exe", "bitwarden.exe", "1password.exe"]
    )
    blocklist_titles: list[str] = Field(default_factory=lambda: ["password manager"])


class VisionConfig(BaseModel):
    enabled: bool = False
    base_url: str = "http://localhost:11434/v1"
    model: str = ""
    api_key: str = ""
    timeout: float = 120.0
    max_side: int = 1280


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    launch: LaunchConfig = Field(default_factory=LaunchConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)


ENV_OVERRIDES = {
    "AYRA_LLM_BASE_URL": ("llm", "base_url"),
    "AYRA_LLM_MODEL": ("llm", "model"),
    "AYRA_LLM_API_KEY": ("llm", "api_key"),
    "AYRA_LLM_SUPPORTS_TOOLS": ("llm", "supports_tools"),
    "AYRA_PORT": ("server", "port"),
    "AYRA_MAX_STEPS": ("agent", "max_steps"),
}


def _expand(value):
    """Espande ${VAR} e %VAR% nelle stringhe, ricorsivamente."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def ensure_config() -> Path:
    """Crea config.yaml dal template se manca. Ritorna il percorso in uso."""
    path = Path(os.environ.get("AYRA_CONFIG") or CONFIG_PATH)
    if not path.exists() and EXAMPLE_PATH.exists() and path == CONFIG_PATH:
        shutil.copyfile(EXAMPLE_PATH, path)
    return path


def load_config(path: Path | None = None) -> Config:
    path = Path(path) if path else ensure_config()
    data: dict = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    data = _expand(data)

    for env_name, (section, key) in ENV_OVERRIDES.items():
        raw = os.environ.get(env_name)
        if raw:
            data.setdefault(section, {})[key] = raw

    return Config(**data)
