#!/usr/bin/env python3
"""
Send an EPUB file to Kindle via email.

Usage:
    python cli/send_to_kindle.py /path/to/book.epub
    python cli/send_to_kindle.py /path/to/book.epub --dry-run
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from utils.kindle_sender import KindleSender


def main():
    parser = argparse.ArgumentParser(description="Send EPUB to Kindle")
    parser.add_argument("epub", type=Path, help="Path to .epub file")
    parser.add_argument("--dry-run", action="store_true", help="Validate without sending")
    parser.add_argument("--kindle-email", help="Override KINDLE_EMAIL env var")
    args = parser.parse_args()

    sender = KindleSender(kindle_email=args.kindle_email)

    try:
        sender.send(args.epub, dry_run=args.dry_run)
        if args.dry_run:
            print(f"[DRY RUN] Config valid. Would send {args.epub.name} to {sender.kindle_email}")
        else:
            print(f"Sent {args.epub.name} to {sender.kindle_email}")
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Send failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
