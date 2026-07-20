"""Configuration loading with safe defaults (no secrets committed)."""  
from __future__ import annotations  
  
import json  
from pathlib import Path  
  
from pydantic import BaseModel, Field  
  
  
class Settings(BaseModel):  
    database_path: str = "backlink_hunter.db"  
    default_concurrency: int = Field(10, ge=1, le=200)  
    per_host_concurrency: int = Field(2, ge=1, le=50)  
    request_timeout_seconds: float = Field(20.0, gt=0)  
    maximum_response_bytes: int = Field(10_485_760, ge=1024)  
    maximum_redirects: int = Field(5, ge=0, le=20)  
    user_agent: str = "BacklinkHunter/1.0"  
    respect_robots_txt: bool = True  
    verify_tls: bool = True  
    log_path: str = "backlink_hunter.log"  
  
    @classmethod  
    def load(cls, path: str | Path = "config.json") -> "Settings":  
        p = Path(path)  
        if p.exists():  
            return cls.model_validate(json.loads(p.read_text(encoding="utf-8")))  
        return cls()
