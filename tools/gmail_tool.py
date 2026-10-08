import os
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import decode_header
import logging
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("gmail_tool")


class GmailTool:
    """Handles sending and reading emails with Gmail using App Passwords."""

    def __init__(self):
        self.user = os.getenv("GMAIL_USER")
        self.password = os.getenv("GMAIL_APP_PASSWORD")

    def _check_credentials(self):
        if not self.user or not self.password:
            raise ValueError(
                "Gmail credentials are not configured. Please set GMAIL_USER and GMAIL_APP_PASSWORD in your .env file."
            )

    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        attachment_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sends an email with optional file attachment."""
        self._check_credentials()

        msg = MIMEMultipart()
        msg["From"] = self.user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # Add attachment if specified
        if attachment_path and os.path.exists(attachment_path):
            filename = os.path.basename(attachment_path)
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={filename}")
            msg.attach(part)

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.user, self.password)
                server.sendmail(self.user, to_email, msg.as_string())
            
            logger.info(f"Email sent successfully to {to_email}!")
            return {"success": True, "to": to_email, "subject": subject}
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return {"success": False, "error": str(e)}

    def read_unread_emails(self, max_count: int = 5) -> List[Dict[str, Any]]:
        """Reads recent unread emails from the INBOX."""
        self._check_credentials()

        emails = []
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.user, self.password)
            mail.select("inbox")

            status, response = mail.search(None, "UNSEEN")
            if status != "OK":
                return []

            msg_ids = response[0].split()
            recent_ids = msg_ids[-max_count:] if len(msg_ids) > max_count else msg_ids

            for mid in reversed(recent_ids):
                status, data = mail.fetch(mid, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Decode subject
                subject, encoding = decode_header(msg.get("Subject", "No Subject"))[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8", errors="ignore")

                # Decode sender
                sender = msg.get("From", "Unknown")

                # Extract text body
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode(errors="ignore")[:500]
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body_text = payload.decode(errors="ignore")[:500]

                emails.append({
                    "id": mid.decode(),
                    "sender": sender,
                    "subject": subject,
                    "date": msg.get("Date", ""),
                    "snippet": body_text.strip(),
                })

            mail.close()
            mail.logout()
            return emails
        except Exception as e:
            logger.error(f"Failed to fetch unread emails: {e}")
            return [{"error": str(e)}]
