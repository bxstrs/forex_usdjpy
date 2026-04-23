'''src/config/loader.py'''
import yaml
from pathlib import Path


BASE_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs"


def load_yaml(relative_path: str) -> dict:
    path = BASE_CONFIG_PATH / relative_path

    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path, "r") as f:
        return yaml.safe_load(f)