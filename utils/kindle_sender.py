#!/usr/bin/env python3
"""
Kindle Email Delivery

Sends EPUB files to a Kindle device via Amazon's Send-to-Kindle email service.
Uses SMTP with stdlib only (no extra dependencies).

Usage:
    from utils.kindle_sender import KindleSender

    sender = KindleSender()
    sender.send("/path/to/book.epub")

Environment variables:
    KINDLE_EMAIL      - Kindle delivery address (xxx@kindle.com)
    SMTP_HOST         - SMTP server (default: smtp.gmail.com)
    SMTP_PORT         - SMTP port (default: 587)
    SMTP_USER         - SMTP username
    SMTP_PASSWORD     - SMTP password (app password for Gmail)
"""

import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)

# Amazon's file size limit for Send-to-Kindle
MAX_FILE_SIZE_MB = 50


class KindleSender:
    """Send EPUB files to Kindle via email."""

    def __init__(
        self,
        kindle_email: str = None,
        smtp_host: str = None,
        smtp_port: int = None,
        smtp_user: str = None,
        smtp_password: str = None,
    ):
        self.kindle_email = kindle_email or os.environ.get("KINDLE_EMAIL", "")
        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.environ.get("SMTP_USER", "")
        self.smtp_password = smtp_password or os.environ.get("SMTP_PASSWORD", "")

    def validate_config(self) -> list[str]:
        """Check configuration. Returns list of missing settings."""
        missing = []
        if not self.kindle_email:
            missing.append("KINDLE_EMAIL")
        if not self.smtp_user:
            missing.append("SMTP_USER")
        if not self.smtp_password:
            missing.append("SMTP_PASSWORD")
        return missing

    def send(self, epub_path: str | Path, dry_run: bool = False) -> bool:
        """
        Send an EPUB file to Kindle.

        Args:
            epub_path: Path to the .epub file
            dry_run: If True, validate everything but don't actually send

        Returns:
            True if sent successfully

        Raises:
            FileNotFoundError: If epub_path doesn't exist
            ValueError: If file is not .epub or exceeds size limit
            RuntimeError: If SMTP config is missing
        """
        epub_path = Path(epub_path)

        # Validate file
        if not epub_path.exists():
            raise FileNotFoundError(f"File not found: {epub_path}")

        if epub_path.suffix.lower() != ".epub":
            raise ValueError(f"Not an EPUB file: {epub_path}")

        file_size_mb = epub_path.stat().st_size / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            raise ValueError(
                f"File too large: {file_size_mb:.1f}MB (max {MAX_FILE_SIZE_MB}MB)"
            )

        # Validate config
        missing = self.validate_config()
        if missing:
            raise RuntimeError(
                f"Missing Kindle config: {', '.join(missing)}. "
                f"Set these as environment variables or pass to KindleSender()."
            )

        logger.info(f"Sending {epub_path.name} ({file_size_mb:.1f}MB) to {self.kindle_email}")

        if dry_run:
            logger.info("[DRY RUN] Would send via %s:%d as %s", self.smtp_host, self.smtp_port, self.smtp_user)
            return True

        # Build email
        msg = MIMEMultipart()
        msg["From"] = self.smtp_user
        msg["To"] = self.kindle_email
        msg["Subject"] = "convert"  # Amazon converts EPUB to Kindle format

        msg.attach(MIMEText("Sent by Book Translator", "plain"))

        # Attach EPUB
        with open(epub_path, "rb") as f:
            part = MIMEBase("application", "epub+zip")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{epub_path.name}"',
        )
        msg.attach(part)

        # Send
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            logger.info("Sent successfully to %s", self.kindle_email)
            return True
        except smtplib.SMTPException as e:
            logger.error("SMTP error: %s", e)
            raise
