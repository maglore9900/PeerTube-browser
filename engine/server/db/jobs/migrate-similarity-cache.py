#!/usr/bin/env python3
"""Convert a legacy-layout similarity cache into the compact layout, writing a new file."""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from data.similarity_cache import (
    NEIGHBOUR,
    ensure_similarity_schema,
    is_legacy_similarity_cache,
    write_similarities,
)
from scripts.cli_format import CompactHelpFormatter

DEFAULT_IN_PATH = Path("engine/server/db/similarity-cache.db")
# Sources per write and commit.
BATCH_SOURCES = 1000


def parse_args() -> argparse.Namespace:
    """Handle parse args."""
    parser = argparse.ArgumentParser(
        description="Convert a legacy similarity cache into a new compact cache file.",
        formatter_class=CompactHelpFormatter,
    )
    parser.add_argument("--in", dest="in_path", type=Path, default=DEFAULT_IN_PATH, help="Legacy cache, opened read-only.")
    parser.add_argument("--out", dest="out_path", type=Path, required=True, help="New compact cache; refused when it exists.")
    return parser.parse_args()


def convert(src: sqlite3.Connection, dst: sqlite3.Connection) -> tuple[int, int]:
    """Write every legacy source and its items, in rank order, into dst; return (sources, items) written."""
    computed_at = {
        (video_id, instance_domain): stamp
        for video_id, instance_domain, stamp in src.execute(
            "SELECT video_id, instance_domain, computed_at FROM similarity_sources"
        )
    }
    total_sources = len(computed_at)
    total_items = 0
    batch: list[tuple[dict, list[dict], int]] = []

    def flush() -> None:
        write_similarities(dst, batch)
        dst.commit()
        batch.clear()

    current: tuple[str, str] | None = None
    items: list[dict] = []
    rows = src.execute(
        """
        SELECT source_video_id, source_instance_domain, similar_video_id, similar_instance_domain, score, rank
        FROM similarity_items
        ORDER BY source_video_id, source_instance_domain, rank
        """
    )
    for source_id, source_domain, video_id, instance_domain, score, rank in rows:
        if (source_id, source_domain) != current:
            if current is not None:
                batch.append(({"video_id": current[0], "instance_domain": current[1]}, items, computed_at.pop(current)))
                if len(batch) >= BATCH_SOURCES:
                    flush()
            current = (source_id, source_domain)
            if current not in computed_at:
                raise RuntimeError(f"similarity_items rows for {source_id}@{source_domain} have no similarity_sources row")
            items = []
        items.append({"video_id": video_id, "instance_domain": instance_domain, "score": score, "rank": rank})
        total_items += 1
    if current is not None:
        batch.append(({"video_id": current[0], "instance_domain": current[1]}, items, computed_at.pop(current)))
    # Sources the legacy file kept with no items stay sources with an empty neighbour list.
    for (video_id, instance_domain), stamp in computed_at.items():
        batch.append(({"video_id": video_id, "instance_domain": instance_domain}, [], stamp))
        if len(batch) >= BATCH_SOURCES:
            flush()
    flush()
    return total_sources, total_items


def main() -> None:
    """Handle main."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    in_path: Path = args.in_path
    out_path: Path = args.out_path
    if out_path.exists():
        raise SystemExit(f"--out {out_path} exists; refusing to overwrite it.")
    if not in_path.is_file():
        raise SystemExit(f"--in {in_path} does not exist.")

    src = sqlite3.connect(f"file:{in_path.resolve().as_posix()}?mode=ro", uri=True)
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    try:
        if not is_legacy_similarity_cache(src):
            raise SystemExit(f"--in {in_path} is not a legacy-layout similarity cache (it has no similarity_items table).")
        tmp_path.unlink(missing_ok=True)
        dst = sqlite3.connect(tmp_path.as_posix())
        try:
            # The temp file is deleted on any failure, so a crash-unsafe write costs nothing.
            dst.execute("PRAGMA synchronous = OFF")
            ensure_similarity_schema(dst)
            sources, items = convert(src, dst)
            written_sources, written_bytes = dst.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(neighbours)), 0) FROM similarity_sources"
            ).fetchone()
        finally:
            dst.close()
        if (written_sources, written_bytes // NEIGHBOUR.size) != (sources, items):
            raise RuntimeError(
                f"count mismatch: legacy sources={sources} items={items}, "
                f"written sources={written_sources} neighbours={written_bytes // NEIGHBOUR.size}"
            )
        os.replace(tmp_path, out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        src.close()

    logging.info(
        "migrated sources=%d neighbours=%d in=%s (%d bytes) out=%s (%d bytes)",
        sources,
        items,
        in_path,
        in_path.stat().st_size,
        out_path,
        out_path.stat().st_size,
    )


if __name__ == "__main__":
    main()
