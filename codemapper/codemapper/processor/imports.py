import re
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Node

from codemapper.processor.parser import CodeParser


@dataclass(frozen=True, slots=True)
class Import:
    module: str
    alias: str | None = None
    is_relative: bool = False
    line: int = 0


@dataclass
class ModuleImports:
    path: Path
    imports: list[Import] = field(default_factory=list)


class ImportExtractor:
    def __init__(self) -> None:
        self._parser = CodeParser()

    def extract(self, path: Path) -> ModuleImports:
        lang = self._parser.detect_language(path)
        if not lang:
            return ModuleImports(path=path)

        content = path.read_text()
        parser = self._parser._get_parser(lang)
        if not parser:
            return ModuleImports(path=path)

        tree = parser.parse(content.encode())
        imports: list[Import] = []

        if lang == "python":
            imports = self._extract_python(tree.root_node, content)
        elif lang in ("javascript", "typescript", "tsx"):
            imports = self._extract_js_ts(tree.root_node, content)
        elif lang == "rust":
            imports = self._extract_rust(tree.root_node, content)
        elif lang == "go":
            imports = self._extract_go(tree.root_node, content)

        return ModuleImports(path=path, imports=imports)

    def _extract_python(self, root: Node, content: str) -> list[Import]:
        imports: list[Import] = []

        for node in self._walk(root):
            if node.type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name" and child.text:
                        imports.append(Import(
                            module=child.text.decode(),
                            line=node.start_point[0] + 1,
                        ))
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        alias_node = child.child_by_field_name("alias")
                        if name_node and name_node.text:
                            imports.append(Import(
                                module=name_node.text.decode(),
                                alias=alias_node.text.decode() if alias_node and alias_node.text else None,
                                line=node.start_point[0] + 1,
                            ))

            elif node.type == "import_from_statement":
                module_node = node.child_by_field_name("module_name")
                is_relative = False
                module_name = ""

                for child in node.children:
                    if child.type == "relative_import":
                        is_relative = True
                        if child.text:
                            module_name = child.text.decode().lstrip(".")
                    elif child.type == "dotted_name" and child.text:
                        module_name = child.text.decode()

                if module_name or is_relative:
                    imports.append(Import(
                        module=module_name or ".",
                        is_relative=is_relative,
                        line=node.start_point[0] + 1,
                    ))

        return imports

    def _extract_js_ts(self, root: Node, content: str) -> list[Import]:
        imports: list[Import] = []

        for node in self._walk(root):
            if node.type == "import_statement":
                source_node = node.child_by_field_name("source")
                if source_node and source_node.text:
                    module = source_node.text.decode().strip("'\"")
                    imports.append(Import(
                        module=module,
                        is_relative=module.startswith("."),
                        line=node.start_point[0] + 1,
                    ))

            elif node.type == "call_expression":
                func = node.child_by_field_name("function")
                if func and func.text and func.text.decode() == "require":
                    args = node.child_by_field_name("arguments")
                    if args and args.child_count > 0:
                        arg = args.children[1] if args.child_count > 1 else args.children[0]
                        if arg.text:
                            module = arg.text.decode().strip("'\"")
                            imports.append(Import(
                                module=module,
                                is_relative=module.startswith("."),
                                line=node.start_point[0] + 1,
                            ))

        return imports

    def _extract_rust(self, root: Node, content: str) -> list[Import]:
        imports: list[Import] = []

        for node in self._walk(root):
            if node.type == "use_declaration":
                path_node = None
                for child in node.children:
                    if child.type in ("scoped_identifier", "identifier", "use_wildcard", "scoped_use_list"):
                        path_node = child
                        break

                if path_node and path_node.text:
                    imports.append(Import(
                        module=path_node.text.decode(),
                        line=node.start_point[0] + 1,
                    ))

            elif node.type == "extern_crate_declaration":
                name_node = node.child_by_field_name("name")
                if name_node and name_node.text:
                    imports.append(Import(
                        module=name_node.text.decode(),
                        line=node.start_point[0] + 1,
                    ))

        return imports

    def _extract_go(self, root: Node, content: str) -> list[Import]:
        imports: list[Import] = []

        for node in self._walk(root):
            if node.type == "import_declaration":
                for child in self._walk(node):
                    if child.type == "interpreted_string_literal" and child.text:
                        module = child.text.decode().strip('"')
                        imports.append(Import(
                            module=module,
                            line=child.start_point[0] + 1,
                        ))
                    elif child.type == "import_spec":
                        path_node = child.child_by_field_name("path")
                        alias_node = child.child_by_field_name("name")
                        if path_node and path_node.text:
                            imports.append(Import(
                                module=path_node.text.decode().strip('"'),
                                alias=alias_node.text.decode() if alias_node and alias_node.text else None,
                                line=child.start_point[0] + 1,
                            ))

        return imports

    def _walk(self, node: Node) -> list[Node]:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._walk(child))
        return nodes
