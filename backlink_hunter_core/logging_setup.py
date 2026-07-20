"""Rotating file logging. Never logs secrets."""  
from __future__ import annotations  
  
import logging  
from logging.handlers import RotatingFileHandler  
from pathlib import Path  
  
_CONFIGURED = False  
  
  
def get_logger(log_path: str = "backlink_hunter.log") -> logging.Logger:  
    global _CONFIGURED  
    logger = logging.getLogger("backlink_hunter")  
    if not _CONFIGURED:  
        logger.setLevel(logging.INFO)  
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)  
        handler = RotatingFileHandler(  
            log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"  
        )  
        handler.setFormatter(  
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")  
        )  
        logger.addHandler(handler)  
        _CONFIGURED = True  
    return logger
