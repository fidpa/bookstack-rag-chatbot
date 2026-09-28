#!/usr/bin/env python3
"""
Create the knowledge-base tables (kb_documents, kb_chunks, kb_chunks_fts, kb_tags).

The app creates them at startup and kb_admin.py on first use, so this script is
only needed to prepare a database ahead of time, or with --force to start over.

    DATABASE_PATH=/path/to/chatbot.db python3 scripts/init_kb_schema.py [--force]
"""

import argparse
import logging
import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chatbot"
    ),
)

from documents.knowledge_base.schema import ensure_kb_schema  # noqa: E402
from utils.database import get_db_path  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create the knowledge-base tables")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Drop all kb_* tables first. Uploaded documents are no longer "
        "listed afterwards (their files stay on disk).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    db_path = get_db_path()
    ensure_kb_schema(db_path, drop=args.force)
    print(f"Knowledge-base schema ready in {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
