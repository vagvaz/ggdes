"""AST parsing for code analysis using tree-sitter."""

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tree_sitter import Language, Parser, Tree

from ggdes.schemas import CodeElement, CodeElementType


@dataclass
class ParseResult:
    """Result of parsing a source file."""

    file_path: str
    language: str
    elements: list[CodeElement]
    tree: Tree
    success: bool
    error_message: Optional[str] = None


class ASTParser:
    """Parse source files using tree-sitter."""

    SUPPORTED_LANGUAGES = {
        ".py": "python",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".hpp": "cpp",
        ".h": "cpp",  # Could be C or C++, we'll try C++ parser
    }

    def __init__(self):
        """Initialize parser with language support."""
        self._parsers: dict[str, Parser] = {}
        self._languages: dict[str, Language] = {}
        self._init_languages()

    def _init_languages(self) -> None:
        """Initialize tree-sitter languages."""
        try:
            from tree_sitter_python import language as python_language

            self._languages["python"] = Language(python_language())
            self._parsers["python"] = Parser(self._languages["python"])
        except ImportError:
            pass

        # C++ support - will be loaded dynamically if available
        self._languages["cpp"] = None
        self._parsers["cpp"] = None

    def _get_parser(self, language: str) -> Optional[Parser]:
        """Get or initialize parser for a language."""
        if language in self._parsers and self._parsers[language]:
            return self._parsers[language]

        if language == "cpp":
            try:
                from tree_sitter_cpp import language as cpp_language

                self._languages["cpp"] = Language(cpp_language())
                self._parsers["cpp"] = Parser(self._languages["cpp"])
                return self._parsers["cpp"]
            except ImportError:
                return None

        return None

    def detect_language(self, file_path: Path) -> Optional[str]:
        """Detect programming language from file extension.

        Args:
            file_path: Path to source file

        Returns:
            Language identifier or None if unsupported
        """
        ext = file_path.suffix.lower()
        return self.SUPPORTED_LANGUAGES.get(ext)

    def parse_file(
        self, file_path: Path, relative_to: Optional[Path] = None
    ) -> ParseResult:
        """Parse a source file and extract code elements.

        Args:
            file_path: Path to source file
            relative_to: Base path for making file_path relative

        Returns:
            ParseResult with extracted elements
        """
        language = self.detect_language(file_path)
        if not language:
            return ParseResult(
                file_path=str(file_path),
                language="unknown",
                elements=[],
                tree=None,
                success=False,
                error_message=f"Unsupported file type: {file_path.suffix}",
            )

        parser = self._get_parser(language)
        if not parser:
            return ParseResult(
                file_path=str(file_path),
                language=language,
                elements=[],
                tree=None,
                success=False,
                error_message=f"Language parser not available: {language}",
            )

        try:
            source_code = file_path.read_text()
        except Exception as e:
            return ParseResult(
                file_path=str(file_path),
                language=language,
                elements=[],
                tree=None,
                success=False,
                error_message=f"Failed to read file: {e}",
            )

        try:
            tree = parser.parse(source_code.encode())
        except Exception as e:
            return ParseResult(
                file_path=str(file_path),
                language=language,
                elements=[],
                tree=None,
                success=False,
                error_message=f"Parse error: {e}",
            )

        # Extract elements based on language
        if language == "python":
            elements = self._extract_python_elements(tree, file_path, relative_to)
        elif language == "cpp":
            elements = self._extract_cpp_elements(tree, file_path, relative_to)
        else:
            elements = []

        # Make file path relative if requested
        display_path = str(file_path)
        if relative_to:
            try:
                display_path = str(file_path.relative_to(relative_to))
            except ValueError:
                pass

        return ParseResult(
            file_path=display_path,
            language=language,
            elements=elements,
            tree=tree,
            success=True,
        )

    def _extract_python_elements(
        self, tree: Tree, file_path: Path, relative_to: Optional[Path] = None
    ) -> list[CodeElement]:
        """Extract code elements from Python AST."""
        elements = []
        root_node = tree.root_node

        # Make file path relative if requested
        display_path = str(file_path)
        if relative_to:
            try:
                display_path = str(file_path.relative_to(relative_to))
            except ValueError:
                pass

        def extract_from_node(node, parent_name: Optional[str] = None):
            """Recursively extract elements from AST nodes."""
            if node.type == "function_definition":
                # Extract function
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = name_node.text.decode()

                    # Get signature from parameters
                    params_node = node.child_by_field_name("parameters")
                    signature = "()"
                    if params_node:
                        signature = params_node.text.decode()

                    # Get docstring
                    docstring = None
                    body_node = node.child_by_field_name("body")
                    if body_node and body_node.children:
                        first_stmt = body_node.children[0]
                        if first_stmt.type == "expression_statement":
                            expr = (
                                first_stmt.children[0] if first_stmt.children else None
                            )
                            if expr and expr.type == "string":
                                docstring = expr.text.decode()

                    # Get decorators
                    decorators = []
                    for child in node.children:
                        if child.type == "decorator":
                            dec_text = child.text.decode().strip()
                            decorators.append(dec_text)

                    element = CodeElement(
                        name=name,
                        element_type=CodeElementType.METHOD
                        if parent_name
                        else CodeElementType.FUNCTION,
                        signature=signature,
                        docstring=docstring,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        file_path=display_path,
                        parent=parent_name,
                        decorators=decorators,
                    )
                    elements.append(element)

                    # Extract nested functions
                    if body_node:
                        for child in body_node.children:
                            extract_from_node(child, name)

            elif node.type == "class_definition":
                # Extract class
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = name_node.text.decode()
                    body_node = node.child_by_field_name("body")

                    # Get docstring
                    docstring = None
                    if body_node and body_node.children:
                        first_stmt = body_node.children[0]
                        if first_stmt.type == "expression_statement":
                            expr = (
                                first_stmt.children[0] if first_stmt.children else None
                            )
                            if expr and expr.type == "string":
                                docstring = expr.text.decode()

                    # Get decorators
                    decorators = []
                    for child in node.children:
                        if child.type == "decorator":
                            dec_text = child.text.decode().strip()
                            decorators.append(dec_text)

                    # Collect method names
                    children = []
                    if body_node:
                        for child in body_node.children:
                            if child.type == "function_definition":
                                method_name_node = child.child_by_field_name("name")
                                if method_name_node:
                                    children.append(method_name_node.text.decode())

                    element = CodeElement(
                        name=name,
                        element_type=CodeElementType.CLASS,
                        docstring=docstring,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        file_path=display_path,
                        children=children,
                        decorators=decorators,
                    )
                    elements.append(element)

                    # Extract methods
                    if body_node:
                        for child in body_node.children:
                            extract_from_node(child, name)

            else:
                # Recurse into other nodes
                for child in node.children:
                    extract_from_node(child, parent_name)

        extract_from_node(root_node)
        return elements

    def _extract_cpp_elements(
        self, tree: Tree, file_path: Path, relative_to: Optional[Path] = None
    ) -> list[CodeElement]:
        """Extract code elements from C++ AST."""
        elements = []
        root_node = tree.root_node

        # Make file path relative if requested
        display_path = str(file_path)
        if relative_to:
            try:
                display_path = str(file_path.relative_to(relative_to))
            except ValueError:
                pass

        def extract_from_node(node, parent_name: Optional[str] = None):
            """Recursively extract elements from AST nodes."""
            # C++ function definition
            if node.type == "function_definition":
                declarator = node.child_by_field_name("declarator")
                if declarator:
                    # Try to find the function name in the declarator
                    name = None
                    signature = "()"

                    if declarator.type == "function_declarator":
                        name_node = declarator.child_by_field_name("declarator")
                        params_node = declarator.child_by_field_name("parameters")
                        if name_node:
                            name = name_node.text.decode()
                        if params_node:
                            signature = params_node.text.decode()

                    if name:
                        element = CodeElement(
                            name=name,
                            element_type=CodeElementType.FUNCTION,
                            signature=signature,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            file_path=display_path,
                            parent=parent_name,
                        )
                        elements.append(element)

            # C++ class definition
            elif node.type in ("class_specifier", "struct_specifier"):
                name_node = node.child_by_field_name("name")
                body_node = node.child_by_field_name("body")

                if name_node:
                    name = name_node.text.decode()
                    children = []

                    if body_node:
                        for child in body_node.children:
                            if child.type in (
                                "function_definition",
                                "field_declaration",
                            ):
                                # Try to extract member names
                                pass

                    element = CodeElement(
                        name=name,
                        element_type=CodeElementType.CLASS,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        file_path=display_path,
                        children=children,
                    )
                    elements.append(element)

            # Recurse
            for child in node.children:
                extract_from_node(child, parent_name)

        extract_from_node(root_node)
        return elements

    def parse_directory(
        self, directory: Path, relative_to: Optional[Path] = None
    ) -> list[ParseResult]:
        """Parse all supported files in a directory.

        Args:
            directory: Directory to scan
            relative_to: Base path for relative paths in output

        Returns:
            List of ParseResults
        """
        results = []

        for file_path in directory.rglob("*"):
            if file_path.is_file() and file_path.suffix in self.SUPPORTED_LANGUAGES:
                result = self.parse_file(file_path, relative_to)
                results.append(result)

        return results

    def get_element_by_name(
        self, results: list[ParseResult], name: str
    ) -> Optional[CodeElement]:
        """Find a code element by name across parse results.

        Args:
            results: List of parse results
            name: Element name to find

        Returns:
            CodeElement if found, None otherwise
        """
        for result in results:
            for element in result.elements:
                if element.name == name:
                    return element
        return None
