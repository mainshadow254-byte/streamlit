"""Shared pytest fixtures."""

from __future__ import annotations

import os

import sys

import pytest

# Ensure repo root on path.

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backlink_hunter_core.config import Config, set_config  # noqa: E402

from backlink_hunter_core.db import Database  # noqa: E402

@pytest.fixture()

def tmp_config(tmp_path):

    cfg = Config()

    cfg.db_path = str(tmp_path / "test.db")

    cfg.log_dir = str(tmp_path / "logs")

    cfg.respect_robots = False

    set_config(cfg)

    return cfg

@pytest.fixture()

def db(tmp_config):

    database = Database(tmp_config)

    yield database

    database.close()

@pytest.fixture(scope="session", autouse=True)

def build_fixtures_once():

    from tests.build_fixtures import build_all

    try:

        build_all()

    except Exception:

        pass

    yield✅ tests/conftest.py is whole.Say next for the actual test modules (normalization/matching, htmlparse/rel, db/migrations/search/export, WAT/WARC/import, verification/SSRF, jobs/checkpoints, empty-index + proof mode).
