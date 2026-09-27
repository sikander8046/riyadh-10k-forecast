import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def make_config(tmp_path):
    def _make(export_dir: Path, **overrides) -> Path:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        cfg["paths"] = {
            "export_dir": str(export_dir),
            "interim_dir": str(tmp_path / "interim"),
            "warehouse": str(tmp_path / "wh.duckdb"),
        }
        cfg.update(overrides)
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(cfg))
        return path

    return _make
