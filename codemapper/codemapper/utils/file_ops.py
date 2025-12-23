from pathlib import Path


class ShadowFS:
    def __init__(self, root: Path, output_dir: str = "maps") -> None:
        self._root = root
        self._maps_dir = root / output_dir

    def source_to_map_path(self, source: Path) -> Path:
        try:
            relative = source.relative_to(self._root)
        except ValueError:
            relative = source
        return self._maps_dir / f"{relative}.md"

    def write_map(self, source: Path, content: str) -> Path:
        map_path = self.source_to_map_path(source)
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(content)
        return map_path

    def read_map(self, source: Path) -> str | None:
        map_path = self.source_to_map_path(source)
        if map_path.exists():
            return map_path.read_text()
        return None

    def map_exists(self, source: Path) -> bool:
        return self.source_to_map_path(source).exists()
