#!/usr/bin/env python3
"""
Send an EPUB file to Kindle via email.

Usage:
    python cli/send_to_kindle.py /path/to/book.epub
    python cli/send_to_kindle.py /path/to/book.epub --dry-run
    python cli/send_to_kindle.py /path/to/book.epub --email extra@kindle.com
    python cli/send_to_kindle.py /path/to/book.epub --email a@kindle.com --email b@kindle.com
"""

import argparse
import logging
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
    parser.add_argument(
        "--email", action="append", dest="emails", metavar="ADDR",
        help="Additional Kindle email (can be repeated). Appends to KINDLE_EMAILS env var.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Build recipient list: env + CLI overrides
    sender = KindleSender()
    if args.emails:
        # Append CLI emails to any from env
        for addr in args.emails:
            if addr not in sender.kindle_emails:
                sender.kindle_emails.append(addr)

    if not sender.kindle_emails:
        print("Error: No Kindle email configured. Set KINDLE_EMAILS env var or use --email.", file=sys.stderr)
        return 1

    try:
        results = sender.send(args.epub, dry_run=args.dry_run)
        if args.dry_run:
            print(f"[DRY RUN] Config valid. Would send {args.epub.name} to:")
            for email in sender.kindle_emails:
                print(f"  - {email}")
        else:
            for email, ok in results.items():
                status = "OK" if ok else "FAILED"
                print(f"  {status}: {email}")
            failed = sum(1 for v in results.values() if not v)
            if failed:
                return 1
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Send failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
