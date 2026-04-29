# n8ngd

`n8ngd` is a PySide6 desktop tool for selecting a local folder, viewing its files, and uploading one file at a time to an n8n webhook.

## Features

- Files tab with folder picker, refresh, and open-folder actions
- Single-selection file list
- Upload selected file to a configured n8n webhook URL
- Settings tab with persisted webhook URL
- Persisted last-used folder path

## Run

Create or use the local virtual environment, then start the app:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m n8ngd
```

Or use the helper script:

```powershell
.\run.ps1
```
