from pathlib import Path

import pathspec


class GitignoreSpec:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._spec = self._load_gitignore()

    def _load_gitignore(self) -> pathspec.PathSpec:
        gitignore_path = self._root / ".gitignore"
        patterns: list[str] = []
        if gitignore_path.exists():
            patterns = gitignore_path.read_text().splitlines()
        patterns.extend([".git/", "__pycache__/", "*.pyc", ".venv/", "node_modules/", ".maps/"])
        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def matches(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self._root)
            return self._spec.match_file(str(relative))
        except ValueError:
            return False

    def filter_paths(self, paths: list[Path]) -> list[Path]:
        return [p for p in paths if not self.matches(p)]
