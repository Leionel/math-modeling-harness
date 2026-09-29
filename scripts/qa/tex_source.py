"""Read the local, statically included TeX source visible to paper checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")
INPUT_COMMAND_RE = re.compile(r"\\(?:input|include)(?![A-Za-z])")
COMMENT_RE = re.compile(r"(?<!\\)%[^\r\n]*")


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    path: Path
    line: int


@dataclass(frozen=True)
class TexSource:
    text: str
    files: tuple[Path, ...]
    spans: tuple[SourceSpan, ...]

    def location(self, offset: int) -> tuple[Path, int] | None:
        return next(
            ((span.path, span.line) for span in self.spans if span.start <= offset < span.end),
            None,
        )


def load_tex_source(entrypoint: Path, project_root: Path) -> TexSource:
    """Expand braced local inputs, retaining exact source locations and failures."""

    root = project_root.resolve()
    input_directory = entrypoint.resolve().parent
    pieces: list[str] = []
    spans: list[SourceSpan] = []
    files: list[Path] = []
    active: set[Path] = set()
    size = 0

    def append(value: str, path: Path, line: int) -> None:
        nonlocal size
        if value:
            pieces.append(value)
            spans.append(SourceSpan(size, size + len(value), path, line))
            size += len(value)

    def visit(raw_path: Path) -> None:
        path = raw_path.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"TeX input escapes project root: {raw_path}") from exc
        if path in active:
            raise ValueError(f"cyclic TeX input: {path}")
        if not path.is_file():
            raise ValueError(f"missing TeX input: {path}")
        if path not in files:
            files.append(path)
        active.add(path)
        try:
            for line_number, source_line in enumerate(path.read_text(encoding="utf-8").splitlines(keepends=True), start=1):
                line = COMMENT_RE.sub("", source_line)
                recognized = {match.start() for match in INPUT_RE.finditer(line)}
                if any(match.start() not in recognized for match in INPUT_COMMAND_RE.finditer(line)):
                    raise ValueError(f"dynamic or unbraced TeX input cannot be inspected: {path}:{line_number}")
                cursor = 0
                for match in INPUT_RE.finditer(line):
                    append(line[cursor:match.start()], path, line_number)
                    target = match.group(1).strip()
                    if "\\" in target or "#" in target:
                        raise ValueError(f"dynamic TeX input cannot be inspected: {path}:{line_number}")
                    # TeX resolves local inputs from the main build directory,
                    # including inputs encountered in nested source files.
                    child = input_directory / target
                    if child.suffix.lower() != ".tex":
                        child = child.with_suffix(".tex")
                    append("\n", path, line_number)
                    visit(child)
                    append("\n", path, line_number)
                    cursor = match.end()
                append(line[cursor:], path, line_number)
        finally:
            active.remove(path)

    visit(entrypoint)
    return TexSource("".join(pieces), tuple(files), tuple(spans))


def read_visible_text(path: Path, project_root: Path) -> str:
    return load_tex_source(path, project_root).text if path.suffix.casefold() == ".tex" else path.read_text(encoding="utf-8")
