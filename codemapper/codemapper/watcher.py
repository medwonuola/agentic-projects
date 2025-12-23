from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from codemapper.utils.gitignore import GitignoreSpec


class CodeEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        root: Path,
        gitignore: GitignoreSpec,
        extensions: set[str],
        on_change: Callable[[Path], None],
    ) -> None:
        self._root = root
        self._gitignore = gitignore
        self._extensions = extensions
        self._on_change = on_change

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self._handle_event(Path(str(event.src_path)))

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self._handle_event(Path(str(event.src_path)))

    def _handle_event(self, path: Path) -> None:
        if path.suffix not in self._extensions:
            return
        if self._gitignore.matches(path):
            return
        self._on_change(path)


class CodeWatcher:
    def __init__(
        self,
        root: Path,
        gitignore: GitignoreSpec,
        extensions: set[str],
        on_change: Callable[[Path], None],
    ) -> None:
        self._root = root
        self._handler = CodeEventHandler(root, gitignore, extensions, on_change)
        self._observer = Observer()

    def start(self) -> None:
        self._observer.schedule(self._handler, str(self._root), recursive=True)
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()

    def is_alive(self) -> bool:
        return self._observer.is_alive()
