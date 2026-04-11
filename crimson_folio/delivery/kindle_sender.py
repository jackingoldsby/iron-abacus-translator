#!/usr/bin/env python3
"""
Kindle Email Delivery

Sends EPUB files to Kindle device(s) via Amazon's Send-to-Kindle email service.
Uses SMTP with stdlib only (no extra dependencies).

Usage:
    from delivery.kindle_sender import KindleSender

    sender = KindleSender()
    results = sender.send("/path/to/book.epub")
    # results: {"jack@kindle.com": True, "other@kindle.com": False}

Environment variables:
    KINDLE_EMAILS     - Comma-separated Kindle addresses (preferred)
    KINDLE_EMAIL      - Single Kindle address (fallback)
    SMTP_HOST         - SMTP server (default: smtp.gmail.com)
    SMTP_PORT         - SMTP port (default: 587)
    SMTP_USER         - SMTP username
    SMTP_PASSWORD     - SMTP password (app password for Gmail)
    SMTP_TIMEOUT      - Connection timeout in seconds (default: 30)
"""

import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

# Amazon's file size limit for Send-to-Kindle
MAX_FILE_SIZE_MB = 50


class KindleSender:
    """Send EPUB files to Kindle via email."""

    def __init__(
        self,
        kindle_emails: List[str] = None,
        smtp_host: str = None,
        smtp_port: int = None,
        smtp_user: str = None,
        smtp_password: str = None,
        smtp_timeout: int = None,
    ):
        # Multi-recipient: KINDLE_EMAILS > KINDLE_EMAIL > empty
        if kindle_emails:
            self.kindle_emails = kindle_emails
        else:
            env_emails = os.environ.get("KINDLE_EMAILS", "")
            if env_emails:
                self.kindle_emails = [e.strip() for e in env_emails.split(",") if e.strip()]
            elif os.environ.get("KINDLE_EMAIL"):
                self.kindle_emails = [os.environ["KINDLE_EMAIL"]]
            else:
                self.kindle_emails = []

        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.environ.get("SMTP_USER", "")
        self.smtp_password = smtp_password or os.environ.get("SMTP_PASSWORD", "")
        self.smtp_timeout = smtp_timeout or int(os.environ.get("SMTP_TIMEOUT", "30"))

    def validate_config(self) -> list[str]:
        """Check configuration. Returns list of missing settings."""
        missing = []
        if not self.kindle_emails:
            missing.append("KINDLE_EMAILS")
        if not self.smtp_user:
            missing.append("SMTP_USER")
        if not self.smtp_password:
            missing.append("SMTP_PASSWORD")
        return missing

    def send(self, epub_path: str | Path, dry_run: bool = False) -> Dict[str, bool]:
        """
        Send an EPUB file to all configured Kindle addresses.

        Args:
            epub_path: Path to the .epub file
            dry_run: If True, validate everything but don't actually send

        Returns:
            Dict mapping each email to True (success) or False (failure)

        Raises:
            FileNotFoundError: If epub_path doesn't exist
            ValueError: If file is not .epub or exceeds size limit
            RuntimeError: If SMTP config is missing
        """
        epub_path = Path(epub_path)

        if not epub_path.exists():
            raise FileNotFoundError(f"File not found: {epub_path}")

        if epub_path.suffix.lower() != ".epub":
            raise ValueError(f"Not an EPUB file: {epub_path}")

        file_size_mb = epub_path.stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            raise ValueError(
                f"File too large: {file_size_mb:.1f}MB (max {MAX_FILE_SIZE_MB}MB)"
            )

        missing = self.validate_config()
        if missing:
            raise RuntimeError(
                f"Missing Kindle config: {', '.join(missing)}. "
                f"Set these as environment variables or pass to KindleSender()."
            )

        recipients = self.kindle_emails
        logger.info(
            f"Sending {epub_path.name} ({file_size_mb:.1f}MB) to {len(recipients)} recipient(s): "
            f"{', '.join(recipients)}"
        )

        if dry_run:
            logger.info("[DRY RUN] Would send via %s:%d as %s", self.smtp_host, self.smtp_port, self.smtp_user)
            return {email: True for email in recipients}

        epub_data = epub_path.read_bytes()

        results = {}
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.smtp_timeout) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)

                for email in recipients:
                    try:
                        msg = self._build_message(email, epub_path.name, epub_data)
                        server.send_message(msg)
                        logger.info("  Sent to %s", email)
                        results[email] = True
                    except smtplib.SMTPException as e:
                        logger.error("  Failed to send to %s: %s", email, e)
                        results[email] = False

        except smtplib.SMTPException as e:
            logger.error("SMTP connection error: %s", e)
            for email in recipients:
                if email not in results:
                    results[email] = False

        succeeded = sum(1 for v in results.values() if v)
        logger.info("Kindle delivery: %d/%d succeeded", succeeded, len(recipients))
        return results

    def _build_message(self, to_email: str, filename: str, epub_data: bytes) -> MIMEMultipart:
        """Build email message with EPUB attachment."""
        msg = MIMEMultipart()
        msg["From"] = f"Iron Abacus <{self.smtp_user}>"
        msg["To"] = to_email
        msg["Subject"] = "convert"  # Amazon converts EPUB to Kindle format

        msg.attach(MIMEText("Sent by Crimson Folio", "plain"))

        part = MIMEBase("application", "octet-stream")
        part.set_payload(epub_data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        part.add_header("Content-Type", "application/epub+zip", name=filename)
        msg.attach(part)
        return msg
