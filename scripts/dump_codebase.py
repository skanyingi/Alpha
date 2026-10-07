"""Write FULL_CODEBASE.txt — concatenated dump of project source."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "FULL_CODEBASE.txt"

INCLUDE_SUFFIX = {
    ".py",
    ".js",
    ".json",
    ".html",
    ".csv",
    ".txt",
    ".md",
    ".ini",
    ".example",
    ".gitignore",
}

INCLUDE_NAMES = {
    "requirements.txt",
    ".gitignore",
    ".env.example",
    "pytest.ini",
    "appsscript.json",
}

SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "venv",
    "audit_logs",
    "node_modules",
}

SKIP_FILES = {
    "FULL_CODEBASE.txt",
}


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.name in INCLUDE_NAMES or path.suffix.lower() in INCLUDE_SUFFIX:
            files.append(path)
    files.sort(key=lambda p: p.as_posix().lower())
    return files


def main() -> None:
    files = iter_files()
    chunks: list[str] = []
    chunks.append(
        "\n".join(
            [
                "=" * 88,
                "HYPERVECTOR RAG — FULL CODEBASE DUMP",
                "Generated for architecture review. Canonical tree is the repo itself.",
                "See ARCHITECTURE.md for diagrams. See README.md for run instructions.",
                f"File count: {len(files)}",
                "=" * 88,
                "",
                "TABLE OF CONTENTS",
                "",
            ]
        )
    )
    for i, path in enumerate(files, start=1):
        rel = path.relative_to(ROOT).as_posix()
        chunks.append(f"  {i:03d}. {rel}")
    chunks.append("")

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.endswith("\n"):
            text += "\n"
        chunks.append("=" * 88)
        chunks.append(f"FILE: {rel}")
        chunks.append("=" * 88)
        chunks.append(text.rstrip("\n"))
        chunks.append("")

    OUT.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(files)} files, {OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
