"""Configuration loader for workforce-graph pipeline."""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
EVIDENCE_CONFIG_PATH = CONFIG_DIR / "evidence.yaml"
DEFAULT_RELEASES_DIR = PROJECT_ROOT / "releases"


def load_sources() -> dict:
    """Load sources.yaml and resolve paths relative to PROJECT_ROOT."""
    config_path = CONFIG_DIR / "sources.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    for source in ("onet", "esco", "wef"):
        if "raw_dir" in cfg[source]:
            cfg[source]["raw_dir"] = str(PROJECT_ROOT / cfg[source]["raw_dir"])

    return cfg


def get_db_path() -> Path:
    """Return path to the DuckDB database file."""
    return DATA_DIR / "workforce_graph.duckdb"
