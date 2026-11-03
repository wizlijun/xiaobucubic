#!/usr/bin/env python3
"""Stage screen-sized fonts, original weather assets and private configuration."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit


def prepare(source, config_path, target):
    config = json.loads(config_path.read_text())
    url = config.get("api_url", "")
    if not isinstance(url, str) or len(url) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("api_url must be a string without control characters")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
        raise ValueError("api_url must be an HTTP(S) endpoint without embedded credentials")
    token = config.get("read_token", "")
    if not isinstance(token, str) or len(token) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in token):
        raise ValueError("read_token must be printable ASCII without control characters")
    for key, low, high, default in (("refresh_seconds", 15, 3600, 60), ("rotate_seconds", 8, 120, 15)):
        value = config.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{key} must be {low}..{high}")
    if type(config.get("auto_rotate", True)) is not bool:
        raise ValueError("auto_rotate must be boolean")
    target.mkdir(parents=True, exist_ok=True)
    destination = target / "apps/xiaobucubic"
    if destination.exists():
        shutil.rmtree(destination)
    hashes = {}
    for original in sorted(source.rglob("*")):
        if not original.is_file() or original.relative_to(source).parts[0] != "assets":
            continue
        relative = original.relative_to(source)
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, output)
        hashes[str(relative)] = hashlib.sha256(original.read_bytes()).hexdigest()
    fonts = Path(__file__).resolve().parents[1] / "assets/fonts"
    manifest = json.loads((fonts / "manifest.json").read_text())
    for name, expected in manifest["sha256"].items():
        original = fonts / name
        if hashlib.sha256(original.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Font checksum mismatch: {name}")
    for original in sorted(fonts.iterdir()):
        if original.is_file():
            output = destination / "font" / original.name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, output)
            hashes[f"font/{original.name}"] = hashlib.sha256(original.read_bytes()).hexdigest()
    output = destination / "config.json"
    output.write_text(json.dumps(config, ensure_ascii=False) + "\n")
    output.chmod(0o600)
    (target.parent / "app-source-sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")


if __name__ == "__main__":
    try:
        prepare(*(Path(arg) for arg in sys.argv[1:]))
    except (OSError, ValueError, TypeError) as error:
        sys.exit(f"App configuration: {error}")
