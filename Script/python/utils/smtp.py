import os
import ssl
import smtplib
import base64
import mimetypes
from pathlib import Path
from email.message import EmailMessage

import msal


smtp_config = {
    'server':'smtp-mail.outlook.com',
    'port':'587',
    'encryption':'STARTTLS',
    'auth':'OAuth2'
}

class EmailService:

    def __init__(self):
        self.tenant_id = os.environ["M365_TENANT_ID"]
        self.client_id = os.environ["M365_CLIENT_ID"]
        self.client_secret = os.environ["M365_CLIENT_SECRET"]
        self.sender = os.environ["M365_SENDER_EMAIL"]

        self.smtp_host = "smtp.office365.com"
        self.smtp_port = 587
        self.timeout = 30

        self.max_attachment_size = 10 * 1024 * 1024
        self.max_total_size = 20 * 1024 * 1024

        self.app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            client_credential=self.client_secret
        )

    def _get_token(self):
        result = self.app.acquire_token_for_client(
            scopes=["https://outlook.office365.com/.default"]
        )

        token = result.get("access_token")

        if not token:
            raise RuntimeError(
                f"OAuth authentication failed: {result.get('error', 'unknown error')}"
            )

        return token

    def _create_message(
        self, to, subject, text, html, cc, bcc, attachments
    ):
        msg = EmailMessage()

        msg["From"] = self.sender
        msg["To"] = ", ".join(to) if isinstance(to, list) else to
        msg["Subject"] = subject

        if cc:
            msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc

        msg.set_content(text or "")

        if html:
            msg.add_alternative(html, subtype="html")

        total_size = 0

        for file in attachments or []:
            path = Path(file)

            if not path.is_file():
                raise ValueError(f"Attachment not found: {path.name}")

            if path.stat().st_size > self.max_attachment_size:
                raise ValueError(f"Attachment too large: {path.name}")

            total_size += path.stat().st_size

            if total_size > self.max_total_size:
                raise ValueError("Total attachment size exceeded.")

            content = path.read_bytes()
            mime, _ = mimetypes.guess_type(path.name)

            maintype, subtype = (
                mime.split("/", 1) if mime else
                ("application", "octet-stream")
            )

            msg.add_attachment(
                content,
                maintype=maintype,
                subtype=subtype,
                filename=path.name
            )

        recipients = []

        for value in (to, cc, bcc):
            if value:
                recipients.extend(
                    value if isinstance(value, list) else [value]
                )

        return msg, list(dict.fromkeys(recipients))

    def send(
        self,
        to,
        subject,
        text=None,
        html=None,
        cc=None,
        bcc=None,
        attachments=None
    ):
        if not to and not cc and not bcc:
            raise ValueError("At least one recipient is required.")

        if not text and not html:
            raise ValueError("Provide a text or HTML body.")

        msg, recipients = self._create_message(
            to, subject, text, html, cc, bcc, attachments
        )

        token = self._get_token()

        auth_string = (
            f"user={self.sender}\x01"
            f"auth=Bearer {token}\x01\x01"
        )

        auth_encoded = base64.b64encode(
            auth_string.encode()
        ).decode()

        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2

        try:
            with smtplib.SMTP(
                self.smtp_host,
                self.smtp_port,
                timeout=self.timeout
            ) as smtp:

                smtp.ehlo()

                if not smtp.has_extn("starttls"):
                    raise RuntimeError("STARTTLS is not supported.")

                smtp.starttls(context=context)
                smtp.ehlo()

                if "xoauth2" not in smtp.esmtp_features.get(
                    "auth", ""
                ).lower():
                    raise RuntimeError("XOAUTH2 is not supported.")

                code, _ = smtp.docmd(
                    "AUTH", f"XOAUTH2 {auth_encoded}"
                )

                if code == 334:
                    code, _ = smtp.docmd("")

                if code != 235:
                    raise RuntimeError(
                        f"SMTP authentication failed: {code}"
                    )

                refused = smtp.send_message(
                    msg,
                    from_addr=self.sender,
                    to_addrs=recipients
                )

                if refused:
                    raise RuntimeError(
                        f"Some recipients were rejected: {len(refused)}"
                    )

        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            raise RuntimeError(
                f"Email delivery failed: {type(exc).__name__}"
            ) from None

        return True
