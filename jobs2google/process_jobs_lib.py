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
PROCESSED_JOB_IDS_FILE_NAME = "processed_job_ids.json"


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


def get_token_file_path() -> Path:
    return get_app_data_directory() / "google_drive_token.json"


def get_processed_job_ids_path() -> Path:
    return get_app_data_directory() / PROCESSED_JOB_IDS_FILE_NAME


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


def extract_job_id(file_path: Path) -> str | None:
    stem = file_path.stem.strip()
    if not stem:
        return None

    _, separator, remainder = stem.partition("_")
    if not separator or not remainder:
        return None

    job_id = remainder.strip()
    return job_id or None


def load_processed_job_ids(processed_job_ids_path: Path) -> set[str]:
    if not processed_job_ids_path.exists():
        return set()

    raw_data = json.loads(processed_job_ids_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise ValueError("processed_job_ids.json must contain a JSON object.")

    raw_job_ids = raw_data.get("job_ids", [])
    if not isinstance(raw_job_ids, list) or not all(isinstance(item, str) for item in raw_job_ids):
        raise ValueError("processed_job_ids.json must contain a 'job_ids' array of strings.")

    return {item.strip() for item in raw_job_ids if item.strip()}


def save_processed_job_ids(processed_job_ids_path: Path, processed_job_ids: set[str]) -> None:
    processed_job_ids_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "job_ids": sorted(processed_job_ids),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    processed_job_ids_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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


def iter_processed_files(source_path: Path) -> list[Path]:
    files: list[Path] = []
    for subfolder_name in ("rejected", "prospects"):
        subfolder_path = source_path / subfolder_name
        if not subfolder_path.exists():
            continue
        files.extend(entry for entry in subfolder_path.iterdir() if entry.is_file())
    return files


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


def find_existing_processed_file(file_path: Path) -> Path | None:
    for subfolder_name in ("rejected", "prospects"):
        existing_path = file_path.parent / subfolder_name / file_path.name
        if existing_path.exists():
            return existing_path
    return None


def build_processed_job_index(source_path: Path) -> dict[str, Path]:
    processed_files = iter_processed_files(source_path)
    job_index: dict[str, Path] = {}
    for processed_file in processed_files:
        job_id = extract_job_id(processed_file)
        if job_id is None:
            continue
        job_index.setdefault(job_id, processed_file)
    return job_index


def process_jobs(source_path: Path, destination_path: str, logger: logging.Logger) -> int:
    config_path = Path(__file__).resolve().parent / "keywords.json"
    keywords, file_patterns = load_keyword_settings(config_path)
    files = iter_source_files(source_path, file_patterns)
    processed_job_ids_path = get_processed_job_ids_path()
    tracked_job_ids = load_processed_job_ids(processed_job_ids_path)
    processed_job_index = build_processed_job_index(source_path)
    known_job_ids = tracked_job_ids | set(processed_job_index)

    logger.info("Loaded %s keyword(s) from %s", len(keywords), config_path)
    logger.info("Found %s top-level file(s) to process in %s", len(files), source_path)
    logger.info("Loaded %s tracked processed job id(s) from %s", len(tracked_job_ids), processed_job_ids_path)
    logger.info("Indexed %s processed file job id(s) from prospects/rejected folders", len(processed_job_index))

    if not files:
        logger.info("No files matched the configured patterns. Nothing to do.")
        return 0

    credentials_path = discover_credentials_path(REPO_ROOT)
    logger.info("Using Google credentials file: %s", credentials_path)

    drive_service = GoogleDriveService()
    token_path = get_token_file_path()
    drive_service.set_token_path(token_path)
    logger.info("Using Google Drive token file: %s", token_path)
    drive_service.connect(str(credentials_path), interactive=False)
    destination_folder_id = drive_service.ensure_folder_path(destination_path)
    logger.info("Resolved Google Drive destination %s to folder id %s", destination_path, destination_folder_id)

    rejected_count = 0
    uploaded_count = 0
    failed_count = 0
    duplicate_count = 0

    for file_path in files:
        logger.info("Processing file: %s", file_path.name)

        job_id = extract_job_id(file_path)
        existing_processed_file = find_existing_processed_file(file_path)
        existing_processed_by_job_id = None if job_id is None else processed_job_index.get(job_id)
        is_tracked_duplicate = job_id is not None and job_id in known_job_ids
        if existing_processed_file is not None or existing_processed_by_job_id is not None or is_tracked_duplicate:
            try:
                file_path.unlink()
            except OSError as exc:
                failed_count += 1
                logger.error(
                    "Duplicate incoming file %s could not be deleted: %s",
                    file_path,
                    exc,
                )
                continue

            duplicate_reason = "tracked processed job id"
            if existing_processed_by_job_id is not None:
                duplicate_reason = f"existing processed job id match in {existing_processed_by_job_id}"
            elif existing_processed_file is not None:
                duplicate_reason = f"existing processed file {existing_processed_file}"

            duplicate_count += 1
            logger.info(
                "Deleted duplicate incoming file %s because it matched %s",
                file_path,
                duplicate_reason,
            )
            continue

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
            if job_id is not None:
                known_job_ids.add(job_id)
                processed_job_index.setdefault(job_id, moved_path)
                save_processed_job_ids(processed_job_ids_path, known_job_ids)
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
        if job_id is not None:
            known_job_ids.add(job_id)
            processed_job_index.setdefault(job_id, moved_path)
            save_processed_job_ids(processed_job_ids_path, known_job_ids)

    logger.info(
        "Processing complete. scanned=%s duplicates_deleted=%s rejected=%s uploaded=%s failed=%s",
        len(files),
        duplicate_count,
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
        print("jobs2google is non-interactive and will not open a browser for Google authorization.", file=sys.stderr)
        print(
            f"If needed, create or refresh the jobs2google token first: {get_token_file_path()}",
            file=sys.stderr,
        )
        print(f"Fatal error. See log file for details: {log_file_path}", file=sys.stderr)
        exit_code = 1

    if exit_code == 0:
        logger.info("Application exiting cleanly. Version %s", __version__)
    else:
        logger.error("Application exiting with error. Version %s", __version__)
    return exit_code
