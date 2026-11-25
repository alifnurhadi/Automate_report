import os

from utils.paths import PYTHON_DIR


def load_env(path=PYTHON_DIR / ".env") -> dict:
    """Read KEY=VALUE lines from .env into os.environ (existing vars win). Never prints values."""
    loaded = {}
    try:
        with open(path, 'r', encoding='utf-8-sig') as rd:
            for line in rd:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                loaded[key.strip()] = value.strip().strip('"\'')
    except FileNotFoundError:
        return {}
    for key, value in loaded.items():
        os.environ.setdefault(key, value)
    return loaded
