from __future__ import annotations

import os
import traceback
from datetime import datetime
from pathlib import Path

from n8ngd import APP_NAME


def _get_bootstrap_log_path() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data) / APP_NAME
    else:
        base_dir = Path.home() / f".{APP_NAME}"

    log_dir = base_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    date_prefix = datetime.now().strftime("%Y%m%d")
    return log_dir / f"{date_prefix}-{APP_NAME}.log"


def _write_bootstrap_failure(exc: BaseException) -> None:
    log_path = _get_bootstrap_log_path()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    message = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"{timestamp} [CRITICAL] Bootstrap startup failure\n")
        log_file.write(message)
        if not message.endswith("\n"):
            log_file.write("\n")


if __name__ == "__main__":
    try:
        from n8ngd.main import main

        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        _write_bootstrap_failure(exc)
        raise
