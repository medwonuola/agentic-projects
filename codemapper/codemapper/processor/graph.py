from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Cycle:
    nodes: list[str]

    def __str__(self) -> str:
        return " → ".join(self.nodes) + " → " + self.nodes[0]


@dataclass
class DependencyStats:
    total_modules: int = 0
    total_imports: int = 0
    external_imports: int = 0
    internal_imports: int = 0
    cycles: list[Cycle] = field(default_factory=list)
    most_imported: list[tuple[str, int]] = field(default_factory=list)
    most_dependencies: list[tuple[str, int]] = field(default_factory=list)


class DependencyGraph:
    def __init__(self) -> None:
        self._edges: dict[str, set[str]] = defaultdict(set)
        self._reverse_edges: dict[str, set[str]] = defaultdict(set)
        self._modules: set[str] = set()
        self._external: set[str] = set()

    def add_module(self, module: str) -> None:
        self._modules.add(module)

    def add_dependency(self, from_module: str, to_module: str, is_external: bool = False) -> None:
        self._edges[from_module].add(to_module)
        self._reverse_edges[to_module].add(from_module)
        self._modules.add(from_module)
        if is_external:
            self._external.add(to_module)
        else:
            self._modules.add(to_module)

    def get_dependencies(self, module: str) -> set[str]:
        return self._edges.get(module, set())

    def get_dependents(self, module: str) -> set[str]:
        return self._reverse_edges.get(module, set())

    def find_cycles(self) -> list[Cycle]:
        cycles: list[Cycle] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self._edges.get(node, set()):
                if neighbor not in self._modules:
                    continue
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor)
                    cycle_nodes = path[cycle_start:]
                    if len(cycle_nodes) > 1:
                        normalized = self._normalize_cycle(cycle_nodes)
                        if not any(c.nodes == normalized for c in cycles):
                            cycles.append(Cycle(nodes=normalized))

            path.pop()
            rec_stack.remove(node)

        for module in self._modules:
            if module not in visited:
                dfs(module)

        return cycles

    def _normalize_cycle(self, nodes: list[str]) -> list[str]:
        if not nodes:
            return nodes
        min_idx = nodes.index(min(nodes))
        return nodes[min_idx:] + nodes[:min_idx]

    def get_stats(self) -> DependencyStats:
        cycles = self.find_cycles()

        import_counts: dict[str, int] = defaultdict(int)
        for deps in self._edges.values():
            for dep in deps:
                import_counts[dep] += 1

        dep_counts = [(m, len(self._edges.get(m, set()))) for m in self._modules]
        imp_counts = [(m, import_counts[m]) for m in self._modules if import_counts[m] > 0]

        return DependencyStats(
            total_modules=len(self._modules),
            total_imports=sum(len(deps) for deps in self._edges.values()),
            external_imports=len(self._external),
            internal_imports=sum(len(deps - self._external) for deps in self._edges.values()),
            cycles=cycles,
            most_imported=sorted(imp_counts, key=lambda x: -x[1])[:10],
            most_dependencies=sorted(dep_counts, key=lambda x: -x[1])[:10],
        )

    def to_mermaid(self, max_nodes: int = 50) -> str:
        lines = ["graph LR"]
        shown_edges: set[tuple[str, str]] = set()
        node_count = 0

        for module in sorted(self._modules)[:max_nodes]:
            short_name = Path(module).stem if "/" in module or "\\" in module else module
            for dep in sorted(self._edges.get(module, set()))[:10]:
                if dep in self._external:
                    continue
                dep_short = Path(dep).stem if "/" in dep or "\\" in dep else dep
                edge = (short_name, dep_short)
                if edge not in shown_edges:
                    shown_edges.add(edge)
                    lines.append(f"    {short_name} --> {dep_short}")
            node_count += 1
            if node_count >= max_nodes:
                break

        if len(lines) == 1:
            lines.append("    NoModules[No internal dependencies found]")

        return "\n".join(lines)


class ProjectAnalyzer:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._graph = DependencyGraph()

    def analyze(self) -> DependencyGraph:
        from codemapper.processor.imports import ImportExtractor
        from codemapper.utils.gitignore import GitignoreSpec

        extractor = ImportExtractor()
        gitignore = GitignoreSpec(self._root)
        extensions = {".py", ".js", ".ts", ".tsx", ".rs", ".go"}

        module_paths: dict[str, Path] = {}

        for file_path in self._root.rglob("*"):
            if file_path.is_dir():
                continue
            if file_path.suffix not in extensions:
                continue
            if gitignore.matches(file_path):
                continue

            try:
                rel_path = file_path.relative_to(self._root)
                module_name = str(rel_path)
                module_paths[module_name] = file_path
                self._graph.add_module(module_name)
            except ValueError:
                continue

        for module_name, file_path in module_paths.items():
            try:
                module_imports = extractor.extract(file_path)
                for imp in module_imports.imports:
                    resolved = self._resolve_import(imp.module, file_path, module_paths)
                    if resolved:
                        self._graph.add_dependency(module_name, resolved, is_external=False)
                    else:
                        self._graph.add_dependency(module_name, imp.module, is_external=True)
            except Exception:
                continue

        return self._graph

    def _resolve_import(self, import_path: str, from_file: Path, known_modules: dict[str, Path]) -> str | None:
        if import_path.startswith("."):
            base_dir = from_file.parent
            parts = import_path.split(".")
            for part in parts:
                if part == "":
                    continue
                elif part == "..":
                    base_dir = base_dir.parent
                else:
                    base_dir = base_dir / part

            for ext in [".py", ".js", ".ts", ".tsx"]:
                candidate = base_dir.with_suffix(ext)
                try:
                    rel = candidate.relative_to(self._root)
                    if str(rel) in known_modules:
                        return str(rel)
                except ValueError:
                    continue

                candidate_init = base_dir / f"__init__{ext}"
                try:
                    rel = candidate_init.relative_to(self._root)
                    if str(rel) in known_modules:
                        return str(rel)
                except ValueError:
                    continue

        for module_path in known_modules:
            module_stem = Path(module_path).stem
            if module_stem == import_path.split(".")[-1]:
                return module_path
            if import_path.replace(".", "/") in module_path:
                return module_path

        return None
