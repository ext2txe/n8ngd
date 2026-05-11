from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from n8ngd.app_paths import get_app_data_directory

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    GOOGLE_DRIVE_IMPORT_ERROR: Exception | None = None
except ImportError as exc:
    Request = None
    Credentials = None
    InstalledAppFlow = None
    build = None
    MediaIoBaseDownload = None
    GOOGLE_DRIVE_IMPORT_ERROR = exc

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


@dataclass(slots=True)
class DriveOption:
    id: str
    name: str
    is_shared_drive: bool = False


@dataclass(slots=True)
class DriveItem:
    id: str
    name: str
    mime_type: str
    parents: list[str]
    web_view_link: str | None = None
    modified_time: str | None = None
    size: int | None = None

    @property
    def is_folder(self) -> bool:
        return self.mime_type == FOLDER_MIME_TYPE


class GoogleDriveService:
    def __init__(self) -> None:
        self._service = None

    @property
    def is_connected(self) -> bool:
        return self._service is not None

    @property
    def is_available(self) -> bool:
        return GOOGLE_DRIVE_IMPORT_ERROR is None

    def get_unavailable_reason(self) -> str:
        if GOOGLE_DRIVE_IMPORT_ERROR is None:
            return ""
        return f"Google Drive support is unavailable: {GOOGLE_DRIVE_IMPORT_ERROR}"

    def connect(self, credentials_path: str) -> None:
        self._ensure_dependencies_available()
        credentials_file = Path(credentials_path)
        if not credentials_file.exists():
            raise FileNotFoundError(f"Google credentials file does not exist: {credentials_file}")

        token_path = self._get_token_path()
        token_path.parent.mkdir(parents=True, exist_ok=True)

        creds: Credentials | None = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json(), encoding="utf-8")
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_drives(self) -> list[DriveOption]:
        self._ensure_dependencies_available()
        self._ensure_connected()

        drives = [DriveOption(id="root", name="My Drive", is_shared_drive=False)]
        response = self._service.drives().list(pageSize=100, fields="drives(id,name)").execute()
        for drive in response.get("drives", []):
            drives.append(DriveOption(id=drive["id"], name=drive["name"], is_shared_drive=True))

        return drives

    def list_folder_items(self, drive: DriveOption, folder_id: str) -> list[DriveItem]:
        self._ensure_dependencies_available()
        self._ensure_connected()

        request_kwargs = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "pageSize": 200,
            "orderBy": "folder,name_natural",
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
            "fields": "files(id,name,mimeType,parents,webViewLink,modifiedTime,size)",
        }

        if drive.is_shared_drive:
            request_kwargs["corpora"] = "drive"
            request_kwargs["driveId"] = drive.id

        response = self._service.files().list(**request_kwargs).execute()
        return [
            DriveItem(
                id=file["id"],
                name=file["name"],
                mime_type=file["mimeType"],
                parents=file.get("parents", []),
                web_view_link=file.get("webViewLink"),
                modified_time=file.get("modifiedTime"),
                size=int(file["size"]) if file.get("size") is not None else None,
            )
            for file in response.get("files", [])
        ]

    def get_preview_text(self, item: DriveItem, *, max_bytes: int = 512_000) -> str:
        self._ensure_dependencies_available()
        self._ensure_connected()

        if item.is_folder:
            return self._format_folder_preview(item)

        if item.size and item.size > max_bytes:
            return self._format_metadata_preview(
                item,
                f"Preview unavailable: file is larger than {max_bytes} bytes.",
            )

        if item.mime_type == GOOGLE_DOC_MIME_TYPE:
            content = self._download_export(item.id, "text/plain")
            return self._decode_preview(item, content)

        if item.mime_type == GOOGLE_SHEET_MIME_TYPE:
            content = self._download_export(item.id, "text/csv")
            return self._decode_preview(item, content)

        if item.mime_type.startswith("application/vnd.google-apps."):
            return self._format_metadata_preview(
                item,
                f"Preview unavailable for Google Drive type: {item.mime_type}",
            )

        content = self._download_media(item.id)
        return self._decode_preview(item, content)

    def get_folder_name(self, item_id: str) -> str:
        self._ensure_dependencies_available()
        self._ensure_connected()
        response = self._service.files().get(
            fileId=item_id,
            fields="id,name",
            supportsAllDrives=True,
        ).execute()
        return response["name"]

    def _download_media(self, file_id: str) -> bytes:
        request = self._service.files().get_media(fileId=file_id, supportsAllDrives=True)
        return self._download_request(request)

    def _download_export(self, file_id: str, mime_type: str) -> bytes:
        request = self._service.files().export_media(fileId=file_id, mimeType=mime_type)
        return self._download_request(request)

    def _download_request(self, request) -> bytes:
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def _decode_preview(self, item: DriveItem, content: bytes) -> str:
        text = content.decode("utf-8", errors="replace")
        return self._format_metadata_preview(item, text)

    def _format_folder_preview(self, item: DriveItem) -> str:
        return self._format_metadata_preview(item, "Folder selected. Double-click to open.")

    def _format_metadata_preview(self, item: DriveItem, body: str) -> str:
        lines = [
            f"Name: {item.name}",
            f"Type: {item.mime_type}",
            f"Modified: {self._format_modified_time(item.modified_time)}",
            f"Size: {item.size if item.size is not None else 'Unknown'}",
            "",
            body,
        ]
        return "\n".join(lines)

    def _ensure_connected(self) -> None:
        if self._service is None:
            raise RuntimeError("Google Drive is not connected.")

    def _ensure_dependencies_available(self) -> None:
        if GOOGLE_DRIVE_IMPORT_ERROR is not None:
            raise RuntimeError(self.get_unavailable_reason())

    def _get_token_path(self) -> Path:
        return get_app_data_directory() / "google_drive_token.json"

    def _format_modified_time(self, modified_time: str | None) -> str:
        if not modified_time:
            return "Unknown"

        try:
            timestamp = datetime.fromisoformat(modified_time.replace("Z", "+00:00"))
        except ValueError:
            return modified_time.replace(",", ".")

        return timestamp.strftime("%Y-%m-%d %H:%M:%S.%f %Z").rstrip("0").rstrip(".")
