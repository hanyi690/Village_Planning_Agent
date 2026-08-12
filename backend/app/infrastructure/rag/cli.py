"""
RAG Knowledge Base CLI Manager

Usage:
    python -m app.infrastructure.rag.cli status
    python -m app.infrastructure.rag.cli delete <source_name>
    python -m app.infrastructure.rag.cli reload <file_path>
    python -m app.infrastructure.rag.cli verify <source_name>

Subcommands:
    status   Show knowledge base statistics
    delete   Remove a document from ChromaDB and all caches
    reload   Delete old data + re-import via standard pipeline
    verify   Check document data consistency (hash, metadata, chunks)
"""

import sys
import argparse
import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure project root is on sys.path for imports
_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # backend/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rag.cli")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_service():
    """Lazy-init RagService singleton."""
    from app.infrastructure.rag.service import RagService
    return RagService.get_instance()


def _compute_file_hash(file_path: Path) -> str:
    """Compute MD5 hash of a file."""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()


def _fmt_result(result: Dict[str, Any]) -> str:
    """Format a result dict for display."""
    status = result.get("status", "unknown")
    if status == "success":
        return f"✓ {result.get('message', 'OK')}"
    elif status == "skipped":
        return f"⊘ {result.get('message', 'Skipped')}"
    else:
        return f"✗ {result.get('message', 'Error')}"


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_status(_args) -> int:
    """Show knowledge base statistics."""
    svc = _get_service()
    stats = svc.get_stats()

    if "message" in stats and stats.get("status") == "error":
        print(f"Error: {stats['message']}")
        return 1

    total_docs = stats.get("total_documents", 0)
    total_chunks = stats.get("total_chunks", 0)
    db_path = stats.get("vector_db_path", "N/A")

    print("=" * 60)
    print("  RAG Knowledge Base Status")
    print("=" * 60)
    print(f"  Total documents : {total_docs}")
    print(f"  Total chunks    : {total_chunks}")
    print(f"  Vector DB path  : {db_path}")

    # Group by category
    docs = stats.get("documents", [])
    if docs:
        by_category: Dict[str, list] = {}
        for d in docs:
            cat = d.get("doc_type", "unknown")
            by_category.setdefault(cat, []).append(d)

        print()
        print("  By doc_type:")
        for cat, items in sorted(by_category.items()):
            chunks = sum(d["chunk_count"] for d in items)
            print(f"    {cat:12s}  {len(items):3d} docs  {chunks:5d} chunks")

    print("=" * 60)
    return 0


def cmd_delete(args) -> int:
    """Delete a document from the knowledge base."""
    source_name = args.source
    svc = _get_service()

    # Check existence first
    if not svc._check_document_exists(source_name):
        print(f"Document not found: {source_name}")
        return 1

    print(f"Deleting: {source_name}")
    result = svc.delete_document(source_name)
    print(_fmt_result(result))

    # Verify
    if not svc._check_document_exists(source_name):
        print("Verified: document removed from knowledge base")
        return 0
    else:
        print("Warning: document may still exist in knowledge base")
        return 1


async def _reload_file(file_path: str) -> Dict[str, Any]:
    """Core reload logic: delete old + add new."""
    svc = _get_service()
    path = Path(file_path)

    if not path.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    if path.suffix.lower() != ".md":
        return {"status": "error", "message": f"Not a Markdown file: {path.suffix}"}

    source_name = path.name
    file_hash = _compute_file_hash(path)

    # Step 1: Delete old data if exists
    if svc._check_document_exists(source_name):
        print(f"  [1/3] Deleting old data: {source_name}")
        del_result = svc.delete_document(source_name)
        if del_result.get("status") != "success":
            return {"status": "error", "message": f"Delete failed: {del_result.get('message')}"}
    else:
        print(f"  [1/3] No existing data for: {source_name}")

    # Step 2: Add via standard pipeline
    print(f"  [2/3] Importing via standard pipeline...")
    add_result = await svc.add_markdown_document(str(path), use_llm_inference=True)

    if add_result.get("status") != "success":
        return add_result

    # Step 3: Verify
    print(f"  [3/3] Verifying import...")
    chunks_added = add_result.get("chunks_added", 0)
    doc_type = add_result.get("doc_type", "N/A")
    category = add_result.get("category", "N/A")
    title = add_result.get("title", "N/A")

    exists = svc._check_document_exists(source_name)
    stored_hash = svc._get_document_hash(source_name)

    print(f"  Result:")
    print(f"    Title      : {title}")
    print(f"    Category   : {category}")
    print(f"    Doc type   : {doc_type}")
    print(f"    Chunks     : {chunks_added}")
    print(f"    File hash  : {file_hash[:12]}...")
    print(f"    Stored hash: {(stored_hash or 'N/A')[:12]}...")
    print(f"    Exists     : {'Yes' if exists else 'No'}")

    if not exists or chunks_added == 0:
        return {"status": "error", "message": "Import verification failed: document not found or 0 chunks"}

    if stored_hash and stored_hash != file_hash:
        return {"status": "error", "message": "Hash mismatch after import"}

    return add_result


def cmd_reload(args) -> int:
    """Delete old data and re-import a Markdown document."""
    file_path = args.file_path
    print(f"Reloading: {file_path}")
    result = asyncio.run(_reload_file(file_path))
    print(_fmt_result(result))
    return 0 if result.get("status") == "success" else 1


def cmd_verify(args) -> int:
    """Verify document data consistency."""
    source_name = args.source
    svc = _get_service()

    print(f"Verifying: {source_name}")

    # Check existence
    exists = svc._check_document_exists(source_name)
    print(f"  Exists in KB    : {'Yes' if exists else 'No'}")
    if not exists:
        print("  Document not found in knowledge base")
        return 1

    # Get stored hash
    stored_hash = svc._get_document_hash(source_name)
    print(f"  Stored hash     : {stored_hash or 'N/A'}")

    # Get document stats
    docs = svc.list_documents()
    doc_info = next((d for d in docs if d["source"] == source_name), None)
    if doc_info:
        print(f"  Chunk count     : {doc_info.get('chunk_count', 0)}")
        print(f"  Doc type        : {doc_info.get('doc_type', 'N/A')}")
    else:
        print("  No stats available")
        return 1

    # Check outline index
    from app.core.settings import OUTLINE_INDEX_DIR
    index_file = OUTLINE_INDEX_DIR / f"{Path(source_name).stem}_index.json"
    if index_file.exists():
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            tree = data.get("tree_index", {})
            print(f"  Outline index   : OK ({len(tree.get('by_id', {}))} nodes)")
        except Exception as e:
            print(f"  Outline index   : INVALID ({e})")
            return 1
    else:
        print(f"  Outline index   : MISSING ({index_file.name})")
        return 1

    # Try to find the source .md file and compare hash
    from app.core.settings import RAG_DOC_DIR
    md_files = list(RAG_DOC_DIR.rglob(source_name))
    if md_files:
        file_hash = _compute_file_hash(md_files[0])
        match = stored_hash == file_hash if stored_hash else False
        print(f"  Source file     : {md_files[0].relative_to(RAG_DOC_DIR)}")
        print(f"  File hash       : {file_hash[:12]}...")
        print(f"  Hash match      : {'Yes' if match else 'No'}")
        if not match:
            print("  ⚠ Hash mismatch — file may have been updated without re-import")
            return 1
    else:
        print(f"  Source file     : Not found in {RAG_DOC_DIR}")

    print("  ✓ Verification passed")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag",
        description="RAG Knowledge Base Manager",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # status
    sub.add_parser("status", help="Show knowledge base statistics")

    # delete
    p_del = sub.add_parser("delete", help="Delete a document from knowledge base")
    p_del.add_argument("source", help="Source filename (e.g. '01 xxx_minerU_parsed.md')")

    # reload
    p_reload = sub.add_parser("reload", help="Delete old + re-import a Markdown document")
    p_reload.add_argument("file_path", help="Path to the .md file to import")

    # verify
    p_ver = sub.add_parser("verify", help="Verify document data consistency")
    p_ver.add_argument("source", help="Source filename to verify")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    dispatch = {
        "status": cmd_status,
        "delete": cmd_delete,
        "reload": cmd_reload,
        "verify": cmd_verify,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
