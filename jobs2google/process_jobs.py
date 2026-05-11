from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from n8ngd import __version__
from n8ngd.google_drive_service import GoogleDriveService

APP_NAME = "jobs2google"
DEFAULT_FILE_PATTERNS = ["*"]


class ArgumentParserError(ValueError):
    pass


class JobsArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ArgumentParserError(message)


def get_app_data_directory() -> Path:
    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / APP_NAME
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        xdg_data_home = os.getenv("XDG_DATA_HOME")
        if xdg_data_home:
            return Path(xdg_data_home) / APP_NAME
        return Path.home() / ".local" / "share" / APP_NAME

    return Path.home() / f".{APP_NAME}"


def get_log_file_path() -> Path:
    log_dir = get_app_data_directory() / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    date_prefix = datetime.now().strftime("%Y%m%d")
    return log_dir / f"{date_prefix}-{APP_NAME}.log"


def configure_logging() -> tuple[logging.Logger, Path]:
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    log_file_path = get_log_file_path()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    formatter.default_msec_format = "%s.%03d"

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger, log_file_path


def build_parser() -> argparse.ArgumentParser:
    parser = JobsArgumentParser(
        description="Process job files, reject keyword matches, and upload prospects to Google Drive.",
    )
    parser.add_argument("source_folder", help="Folder containing job files to process.")
    parser.add_argument(
        "destination_path",
        help="Google Drive destination path, for example 'jobs2google' or '/some/path'.",
    )
    return parser


def normalize_source_folder(source_folder: str) -> Path:
    source_path = Path(source_folder).expanduser().resolve(strict=False)
    if not source_path.exists():
        raise FileNotFoundError(f"Source folder does not exist: {source_path}")
    if not source_path.is_dir():
        raise NotADirectoryError(f"Source path is not a folder: {source_path}")
    return source_path


def normalize_drive_path(destination_path: str) -> str:
    trimmed = destination_path.strip()
    if not trimmed:
        raise ValueError("Destination Google Drive path is required.")

    normalized = trimmed.replace("\\", "/")
    parts = [part.strip() for part in normalized.split("/") if part.strip()]
    if not parts:
        raise ValueError("Destination Google Drive path must include at least one folder.")

    return "/" + "/".join(parts)


def get_destination_path(destination_root: str, run_date: datetime) -> str:
    return f"{destination_root}/{run_date.strftime('%Y%m%d')}"


def load_keyword_settings(config_path: Path) -> tuple[list[str], list[str]]:
    if not config_path.exists():
        raise FileNotFoundError(f"Keyword settings file does not exist: {config_path}")

    raw_data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise ValueError("keywords.json must contain a JSON object.")

    raw_keywords = raw_data.get("keywords")
    if not isinstance(raw_keywords, list):
        raise ValueError("keywords.json must contain a 'keywords' array.")

    keywords: list[str] = []
    for entry in raw_keywords:
        if not isinstance(entry, str):
            raise ValueError("Every keyword in keywords.json must be a string.")
        keyword = entry.strip()
        if keyword:
            keywords.append(keyword)

    raw_patterns = raw_data.get("file_patterns", DEFAULT_FILE_PATTERNS)
    if not isinstance(raw_patterns, list) or not all(isinstance(item, str) for item in raw_patterns):
        raise ValueError("'file_patterns' in keywords.json must be an array of strings.")

    file_patterns = [pattern.strip() for pattern in raw_patterns if pattern.strip()]
    if not file_patterns:
        file_patterns = DEFAULT_FILE_PATTERNS.copy()

    return keywords, file_patterns


def discover_credentials_path(repo_root: Path) -> Path:
    env_candidates = [
        os.getenv("JOBS2GOOGLE_GOOGLE_CREDENTIALS"),
        os.getenv("N8NGD_GOOGLE_CREDENTIALS"),
    ]
    for candidate in env_candidates:
        if not candidate:
            continue
        credentials_path = Path(candidate).expanduser().resolve(strict=False)
        if credentials_path.exists() and credentials_path.is_file():
            return credentials_path
        raise FileNotFoundError(f"Google credentials file from environment does not exist: {credentials_path}")

    matches = sorted(repo_root.glob("client_secret*.json"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RuntimeError(
            "Multiple Google client secret files were found. Set JOBS2GOOGLE_GOOGLE_CREDENTIALS to choose one."
        )

    raise FileNotFoundError(
        "Google OAuth credentials file not found. Set JOBS2GOOGLE_GOOGLE_CREDENTIALS or add one client_secret*.json file."
    )


def iter_source_files(source_path: Path, file_patterns: list[str]) -> list[Path]:
    files = [entry for entry in source_path.iterdir() if entry.is_file()]
    filtered = [
        entry for entry in files if any(fnmatch.fnmatch(entry.name.lower(), pattern.lower()) for pattern in file_patterns)
    ]
    return sorted(filtered, key=lambda item: item.name.lower())


def find_matching_keywords(file_path: Path, keywords: list[str]) -> list[str]:
    content = file_path.read_text(encoding="utf-8", errors="replace").lower()
    matches = [keyword for keyword in keywords if keyword.lower() in content]
    return matches


def move_file_to_subfolder(file_path: Path, subfolder_name: str) -> Path:
    destination_dir = file_path.parent / subfolder_name
    destination_dir.mkdir(parents=True, exist_ok=True)

    destination_path = destination_dir / file_path.name
    if not destination_path.exists():
        shutil.move(str(file_path), str(destination_path))
        return destination_path

    stem = file_path.stem
    suffix = file_path.suffix
    counter = 1
    while True:
        candidate = destination_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            shutil.move(str(file_path), str(candidate))
            return candidate
        counter += 1


def process_jobs(source_path: Path, destination_path: str, logger: logging.Logger) -> int:
    config_path = Path(__file__).resolve().parent / "keywords.json"
    keywords, file_patterns = load_keyword_settings(config_path)
    files = iter_source_files(source_path, file_patterns)

    logger.info("Loaded %s keyword(s) from %s", len(keywords), config_path)
    logger.info("Found %s top-level file(s) to process in %s", len(files), source_path)

    if not files:
        logger.info("No files matched the configured patterns. Nothing to do.")
        return 0

    credentials_path = discover_credentials_path(REPO_ROOT)
    logger.info("Using Google credentials file: %s", credentials_path)

    drive_service = GoogleDriveService()
    drive_service.connect(str(credentials_path))
    destination_folder_id = drive_service.ensure_folder_path(destination_path)
    logger.info("Resolved Google Drive destination %s to folder id %s", destination_path, destination_folder_id)

    rejected_count = 0
    uploaded_count = 0
    failed_count = 0

    for file_path in files:
        logger.info("Processing file: %s", file_path.name)
        try:
            matches = find_matching_keywords(file_path, keywords)
        except OSError as exc:
            failed_count += 1
            logger.error("Failed to read %s: %s", file_path, exc)
            continue

        if matches:
            try:
                moved_path = move_file_to_subfolder(file_path, "rejected")
            except OSError as exc:
                failed_count += 1
                logger.error("Failed to move rejected file %s: %s", file_path, exc)
                continue

            rejected_count += 1
            logger.info("Rejected %s due to keyword match(es): %s", file_path.name, ", ".join(matches))
            logger.info("Moved rejected file to %s", moved_path)
            continue

        try:
            file_id = drive_service.upload_file_to_folder(file_path, destination_folder_id)
        except Exception as exc:
            failed_count += 1
            logger.error("Failed to upload %s to Google Drive destination %s: %s", file_path, destination_path, exc)
            continue

        try:
            moved_path = move_file_to_subfolder(file_path, "prospects")
        except OSError as exc:
            failed_count += 1
            logger.error("Uploaded %s but failed to move it to prospects: %s", file_path, exc)
            continue

        uploaded_count += 1
        logger.info("Uploaded %s to Google Drive with id %s", file_path.name, file_id)
        logger.info("Moved uploaded file to %s", moved_path)

    logger.info(
        "Processing complete. scanned=%s rejected=%s uploaded=%s failed=%s",
        len(files),
        rejected_count,
        uploaded_count,
        failed_count,
    )
    return 0 if failed_count == 0 else 1


def main() -> int:
    logger, log_file_path = configure_logging()
    logger.info("Application startup complete. Version %s", __version__)
    logger.info("Log file: %s", log_file_path)

    try:
        args = build_parser().parse_args()
        source_path = normalize_source_folder(args.source_folder)
        destination_root = normalize_drive_path(args.destination_path)
        destination_path = get_destination_path(destination_root, datetime.now())
        logger.info("Source folder: %s", source_path)
        logger.info("Google Drive destination path: %s", destination_path)
        exit_code = process_jobs(source_path, destination_path, logger)
    except ArgumentParserError as exc:
        logger.error("Argument error: %s", exc)
        print(f"Argument error: {exc}", file=sys.stderr)
        exit_code = 1
    except Exception:
        logger.exception("Job processing failed.")
        print(f"Fatal error. See log file for details: {log_file_path}", file=sys.stderr)
        exit_code = 1

    if exit_code == 0:
        logger.info("Application exiting cleanly. Version %s", __version__)
    else:
        logger.error("Application exiting with error. Version %s", __version__)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
