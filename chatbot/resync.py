#!/usr/bin/env python3
"""Rebuild the BookStack RAG index from the BookStack API.

Webhooks keep the index current in normal operation. This is the repair path for
an index that has drifted: webhooks that failed silently for a while, or content
deleted before the endpoint learned to remove it.

Runs inside the chatbot container, where the BookStack credentials and
DATABASE_PATH are already in the environment:

    docker compose -f docker/docker-compose.yml exec chatbot \
        python resync.py --full-resync

It writes to the same SQLite file as the running app, so prefer a quiet moment;
`--dry-run` only reads.
"""

import argparse
import logging
import os
import sys

from bookstack.api_client import get_bookstack_client
from bookstack.sync_service import ContentSyncService

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resync.py",
        description="Rebuild the BookStack RAG index from the BookStack API.",
    )
    parser.add_argument(
        "--full-resync",
        action="store_true",
        help="Walk every book, chapter and page and reindex it",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Keep index rows for content BookStack no longer reports",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what the index holds now and exit without writing",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(levelname)s: %(message)s",
    )

    service = ContentSyncService(get_bookstack_client())

    if args.dry_run:
        stats = service.get_sync_stats()
        print(f"Index holds {stats['total_content']} items: {stats['content_counts']}")
        print(f"Last sync: {stats['last_sync']}")
        return 0

    if not args.full_resync:
        parser.error("nothing to do: pass --full-resync (or --dry-run)")

    result = service.sync_all(prune=not args.no_prune)
    print(
        f"Books: {result['books']}, chapters: {result['chapters']}, "
        f"pages: {result['pages']}, pruned: {result['removed']}, "
        f"errors: {result['errors']}"
    )
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
