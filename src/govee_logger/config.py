import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path("/etc/govee-logger/config.toml")


@dataclass
class Config:
    db_path: Path = Path("/var/lib/govee-logger/readings.db")
    scan_seconds: float = 60
    adapter: str | None = None
    aliases: dict[str, str] = field(default_factory=dict)


def load(path: Path | None) -> Config:
    if path is None:
        if not DEFAULT_CONFIG.exists():
            return Config()
        path = DEFAULT_CONFIG
    with path.open("rb") as f:
        raw = tomllib.load(f)
    cfg = Config()
    if "db_path" in raw:
        cfg.db_path = Path(raw["db_path"])
    cfg.scan_seconds = float(raw.get("scan_seconds", cfg.scan_seconds))
    cfg.adapter = raw.get("adapter") or None
    cfg.aliases = {k.upper(): v for k, v in raw.get("aliases", {}).items()}
    return cfg
