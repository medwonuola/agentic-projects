from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript
import tree_sitter_rust
import tree_sitter_go
from tree_sitter import Language, Parser, Node


class SymbolKind(StrEnum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    kind: SymbolKind
    code: str
    start_line: int
    end_line: int
    signature: str


class CodeParser:
    _LANGUAGES: dict[str, Language] = {}
    _QUERIES: dict[str, tuple[str, ...]] = {
        "python": ("function_definition", "class_definition"),
        "javascript": ("function_declaration", "class_declaration", "arrow_function", "method_definition"),
        "typescript": ("function_declaration", "class_declaration", "arrow_function", "method_definition"),
        "tsx": ("function_declaration", "class_declaration", "arrow_function", "method_definition"),
        "rust": ("function_item", "impl_item", "struct_item"),
        "go": ("function_declaration", "method_declaration", "type_declaration"),
    }

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}
        self._init_languages()

    def _init_languages(self) -> None:
        if not CodeParser._LANGUAGES:
            CodeParser._LANGUAGES = {
                "python": Language(tree_sitter_python.language()),
                "javascript": Language(tree_sitter_javascript.language()),
                "typescript": Language(tree_sitter_typescript.language_typescript()),
                "tsx": Language(tree_sitter_typescript.language_tsx()),
                "rust": Language(tree_sitter_rust.language()),
                "go": Language(tree_sitter_go.language()),
            }

    def _get_parser(self, lang: str) -> Parser | None:
        if lang not in CodeParser._LANGUAGES:
            return None
        if lang not in self._parsers:
            parser = Parser(CodeParser._LANGUAGES[lang])
            self._parsers[lang] = parser
        return self._parsers[lang]

    def detect_language(self, path: Path) -> str | None:
        ext_map = {
            ".py": "python",
            ".pyi": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".mjs": "javascript",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".rs": "rust",
            ".go": "go",
        }
        return ext_map.get(path.suffix)

    def extract_symbols(self, content: str, lang: str) -> list[Symbol]:
        parser = self._get_parser(lang)
        if not parser:
            return []
        tree = parser.parse(content.encode())
        node_types = self._QUERIES.get(lang, ())
        symbols: list[Symbol] = []
        self._traverse(tree.root_node, node_types, content, symbols, lang)
        return symbols

    def _traverse(self, node: Node, types: tuple[str, ...], content: str, symbols: list[Symbol], lang: str) -> None:
        if node.type in types:
            symbol = self._node_to_symbol(node, content, lang)
            if symbol:
                symbols.append(symbol)
        for child in node.children:
            self._traverse(child, types, content, symbols, lang)

    def _node_to_symbol(self, node: Node, content: str, lang: str) -> Symbol | None:
        name = self._extract_name(node, lang)
        if not name:
            return None
        kind = self._determine_kind(node.type)
        code = content[node.start_byte:node.end_byte]
        signature = self._extract_signature(node, content, lang)
        return Symbol(
            name=name,
            kind=kind,
            code=code,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            signature=signature,
        )

    def _extract_name(self, node: Node, lang: str) -> str | None:
        name_fields = ["name", "declarator"]
        for field in name_fields:
            name_node = node.child_by_field_name(field)
            if name_node:
                if name_node.type == "identifier":
                    return name_node.text.decode() if name_node.text else None
                id_node = name_node.child_by_field_name("name")
                if id_node and id_node.text:
                    return id_node.text.decode()
        for child in node.children:
            if child.type == "identifier" and child.text:
                return child.text.decode()
        return None

    def _determine_kind(self, node_type: str) -> SymbolKind:
        if "class" in node_type or "struct" in node_type or "impl" in node_type:
            return SymbolKind.CLASS
        if "method" in node_type:
            return SymbolKind.METHOD
        return SymbolKind.FUNCTION

    def _extract_signature(self, node: Node, content: str, lang: str) -> str:
        first_line_end = content.find("\n", node.start_byte)
        if first_line_end == -1:
            first_line_end = node.end_byte
        sig = content[node.start_byte:first_line_end].strip()
        if lang == "python" and sig.endswith(":"):
            sig = sig[:-1].strip()
        return sig
