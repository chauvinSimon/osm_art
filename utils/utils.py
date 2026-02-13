from datetime import datetime
from pathlib import Path

import yaml

project_root_dir = Path(__file__).parent.parent
ignored_dir = project_root_dir / "ignored"
svg_dir = ignored_dir / "svg"
osm_dir = ignored_dir / "osm"
res_dir = ignored_dir / "res"
names_dir = ignored_dir / "names"
config_path = project_root_dir / "config.yaml"
logging_config_path = project_root_dir / "config.logging.yaml"


def load_config():
    return yaml_load(config_path)


def load_logging_config():
    return yaml_load(logging_config_path)


# YAML utils
def yaml_load(file_path: Path):
    """Load data from a YAML file."""
    if not file_path.exists():
        raise FileNotFoundError(f"yaml file not found: {file_path}")
    with file_path.open("r") as f:
        return yaml.safe_load(f)


def yaml_dump(data, file_path: Path):
    """Dump data to a YAML file."""
    with file_path.open("w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)


def get_timestamp(use_ms: bool = False) -> str:
    now = datetime.now()
    if use_ms:
        # [:18] = Truncate microseconds to 3 digits for milliseconds
        return now.strftime("%Y%m%d_%H%M%S_%f")[:18]
    return now.strftime("%Y%m%d_%H%M%S")
