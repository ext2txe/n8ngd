from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from n8ngd.google_drive_service import GoogleDriveService

from jobs2google.process_jobs_lib import discover_credentials_path, get_token_file_path


def main() -> int:
    credentials_path = discover_credentials_path(REPO_ROOT)
    token_path = get_token_file_path()

    drive_service = GoogleDriveService()
    drive_service.set_token_path(token_path)
    drive_service.connect(str(credentials_path), interactive=True)

    print(f"jobs2google authorization complete.")
    print(f"Credentials file: {credentials_path}")
    print(f"Token file: {token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
