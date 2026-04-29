from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib import error, parse, request


@dataclass(slots=True)
class UploadResult:
    success: bool
    message: str
    status_code: int | None = None


def validate_webhook_url(webhook_url: str) -> None:
    parsed = parse.urlparse(webhook_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("N8N Webhook URL must be a valid http or https URL.")


def upload_file(file_path: str, webhook_url: str) -> UploadResult:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return UploadResult(False, f"Selected file is not available: {path}")

    validate_webhook_url(webhook_url)

    boundary = f"----n8ngd-{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    file_bytes = path.read_bytes()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            status_code = getattr(response, "status", None)
            return UploadResult(True, "Upload completed successfully.", status_code)
    except error.HTTPError as exc:
        return UploadResult(False, f"Upload failed with HTTP {exc.code}.", exc.code)
    except error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return UploadResult(False, f"Upload failed: {reason}")
    except Exception as exc:  # pragma: no cover - safety net for GUI use
        return UploadResult(False, f"Upload failed: {exc}")
