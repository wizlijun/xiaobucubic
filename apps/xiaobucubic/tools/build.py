#!/usr/bin/env python3
"""Build an SD-card layout ZIP. Runtime credentials/cache are never included."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
out = root/"dist/xiaobucubic-1.0.0.zip"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
    for file in sorted((root/"package").rglob("*")):
        if file.is_file() and file.name not in ("cache.json", "diagnostics.json"):
            archive.write(file, Path("apps/xiaobucubic")/file.relative_to(root/"package"))
print(out)
