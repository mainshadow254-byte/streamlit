"""Central configuration for Backlink Hunter."""

from __future__ import annotations

import json

import os

from dataclasses import dataclass, field, asdict

from pathlib import Path

from typing import Any, Dict, Optional

DEFAULT_CONFIG_FILE = "config.json"

DEFAULT_DB_PATH = "backlinks.db"

DEFAULT_TIMEOUT = 20.0

DEFAULT_MAX_REDIRECTS = 5

DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024

DEFAULT_MAX_DECOMPRESSED_BYTES = 200 * 1024 * 1024

DEFAULT_USER_AGENT = (

    "BacklinkHunter/2.0 (+https://github.com/mainshadow254-byte/streamlit; "

    "respects robots.txt)"

)

DEFAULT_GLOBAL_RATE = 5.0

DEFAULT_PER_HOST_RATE = 1.0

DEFAULT_BATCH_SIZE = 500

DEFAULT_QUEUE_MAXSIZE = 2000

DEFAULT_CHECKPOINT_EVERY = 2000

def _env_bool(name: str, default: bool) -> bool:

    val = os.environ.get(name)

    if val is None:

        return default

    return val.strip().lower() in {"1", "true", "yes", "on"}

def _env_float(name: str, default: float) -> float:

    val = os.environ.get(name)

    if val is None:

        return default

    try:

        return float(val)

    except ValueError:

        return default

def _env_int(name: str, default: int) -> int:

    val = os.environ.get(name)

    if val is None:

        return default

    try:

        return int(val)

    except ValueError:

        return default

@dataclass

class Config:

    db_backend: str = "sqlite"

    db_path: str = DEFAULT_DB_PATH

    postgres_dsn: Optional[str] = None

    sqlite_wal: bool = True

    timeout: float = DEFAULT_TIMEOUT

    max_redirects: int = DEFAULT_MAX_REDIRECTS

    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES

    max_decompressed_bytes: int = DEFAULT_MAX_DECOMPRESSED_BYTES

    user_agent: str = DEFAULT_USER_AGENT

    respect_robots: bool = True

    verify_tls: bool = True

    global_rate: float = DEFAULT_GLOBAL_RATE

    per_host_rate: float = DEFAULT_PER_HOST_RATE

    batch_size: int = DEFAULT_BATCH_SIZE

    queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE

    checkpoint_every: int = DEFAULT_CHECKPOINT_EVERY

    max_download_bytes: int = 0

    min_free_disk_bytes: int = 500 * 1024 * 1024

    cc_index_server: str = "https://index.commoncrawl.org"

    cc_data_host: str = "https://data.commoncrawl.org"

    cc_collinfo_url: str = "https://index.commoncrawl.org/collinfo.json"

    log_dir: str = "logs"

    log_level: str = "INFO"

    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod

    def load(cls, path: Optional[str] = None) -> "Config":

        cfg = cls()

        cfg_path = Path(path or os.environ.get("BLH_CONFIG", DEFAULT_CONFIG_FILE))

        if cfg_path.exists():

            try:

                data = json.loads(cfg_path.read_text(encoding="utf-8"))

                for key, value in data.items():

                    if hasattr(cfg, key):

                        setattr(cfg, key, value)

                    else:

                        cfg.extra[key] = value

            except (json.JSONDecodeError, OSError):

                pass

        cfg.db_backend = os.environ.get("BLH_DB_BACKEND", cfg.db_backend)

        cfg.db_path = os.environ.get("BLH_DB_PATH", cfg.db_path)

        cfg.postgres_dsn = os.environ.get("BLH_POSTGRES_DSN", cfg.postgres_dsn)

        cfg.sqlite_wal = _env_bool("BLH_SQLITE_WAL", cfg.sqlite_wal)

        cfg.timeout = _env_float("BLH_TIMEOUT", cfg.timeout)

        cfg.max_redirects = _env_int("BLH_MAX_REDIRECTS", cfg.max_redirects)

        cfg.max_response_bytes = _env_int("BLH_MAX_RESPONSE_BYTES", cfg.max_response_bytes)

        cfg.user_agent = os.environ.get("BLH_USER_AGENT", cfg.user_agent)

        cfg.respect_robots = _env_bool("BLH_RESPECT_ROBOTS", cfg.respect_robots)

        cfg.global_rate = _env_float("BLH_GLOBAL_RATE", cfg.global_rate)

        cfg.per_host_rate = _env_float("BLH_PER_HOST_RATE", cfg.per_host_rate)

        cfg.batch_size = _env_int("BLH_BATCH_SIZE", cfg.batch_size)

        cfg.log_level = os.environ.get("BLH_LOG_LEVEL", cfg.log_level)

        cfg.log_dir = os.environ.get("BLH_LOG_DIR", cfg.log_dir)

        cfg.verify_tls = True

        return cfg

    def to_dict(self) -> Dict[str, Any]:

        return asdict(self)

_ACTIVE: Optional[Config] = None

def get_config(path: Optional[str] = None) -> Config:

    global _ACTIVE

    if _ACTIVE is None:

        _ACTIVE = Config.load(path)

    return _ACTIVE

def set_config(cfg: Config) -> None:

    global _ACTIVE

    _ACTIVE = cfg
