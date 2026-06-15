from pathlib import Path


class FileService:
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)

    def get_absolute_path(self, path: str) -> str:
        raw = Path(path)
        if raw.is_absolute():
            return str(raw)
        return str((self.base_dir / raw).resolve())
