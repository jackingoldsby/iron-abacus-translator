#!/usr/bin/env python3
"""
CLI: assign — manage image-to-work assignments.

Usage:
    python -m cli.assign --work D1379 --image ~/.amber_inkstone/images/ming_dynasty/abc123.jpg
    python -m cli.assign --work D1379 --image-id abc123def456
    python -m cli.assign --list
    python -m cli.assign --work D1379 --clear
"""

import argparse
import hashlib
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from catalog.portfolio_db import PortfolioDB


def main():
    parser = argparse.ArgumentParser(
        description="Amber Inkstone — Assign images to works"
    )
    parser.add_argument("--work", type=str, help="Work number (e.g. D1379)")
    parser.add_argument(
        "--image", type=Path,
        help="Path to image file (resolves to image_id via filename)",
    )
    parser.add_argument(
        "--image-id", type=str,
        help="Image ID directly (md5 hash prefix from portfolio)",
    )
    parser.add_argument("--clear", action="store_true", help="Clear assignment for work")
    parser.add_argument("--list", action="store_true", help="List all assignments")
    parser.add_argument("--portfolio-db", type=Path, help="Override portfolio DB path")

    args = parser.parse_args()
    db = PortfolioDB(args.portfolio_db)

    if args.list:
        return _list_assignments(db)

    if not args.work:
        parser.print_help()
        return 0

    if args.clear:
        db.clear_assignment(args.work)
        print(f"Cleared assignment for {args.work}")
        return 0

    # Resolve image_id
    image_id = args.image_id
    if args.image and not image_id:
        # Extract image_id from filename (filename is {image_id}.ext)
        image_id = args.image.stem.replace("_thumb", "")

    if not image_id:
        print("Error: provide --image or --image-id")
        return 1

    # Verify image exists in portfolio
    img = db.get_image(image_id)
    if not img:
        # Try matching by prefix
        all_images = db.get_all_images()
        matches = [i for i in all_images if i.image_id.startswith(image_id)]
        if len(matches) == 1:
            img = matches[0]
            image_id = img.image_id
        elif len(matches) > 1:
            print(f"Ambiguous image ID prefix '{image_id}' — matches {len(matches)} images")
            for m in matches:
                print(f"  {m.image_id} — {m.title[:50]}")
            return 1
        else:
            print(f"Image ID '{image_id}' not found in portfolio")
            return 1

    db.assign_image(args.work, image_id)
    print(f"Assigned: {args.work} -> {img.title[:60]} ({image_id[:12]})")
    print(f"  Path: {img.cached_path}")
    return 0


def _list_assignments(db: PortfolioDB):
    """List all work-to-image assignments."""
    assignments = db.list_assignments()

    if not assignments:
        print("No assignments yet.")
        return 0

    print(f"\n{'Work':<10} {'Image ID':<14} {'Title':<45} {'Assigned'}")
    print("-" * 85)

    for a in assignments:
        img = db.get_image(a.image_id)
        title = img.title[:43] if img else "?"
        date = a.assigned_at.strftime("%Y-%m-%d") if a.assigned_at else "?"
        print(f"{a.work_number:<10} {a.image_id[:12]:<14} {title:<45} {date}")

    print()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
