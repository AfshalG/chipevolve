"""The webview is dead without its CSS/JS, and nothing at runtime says so.

VS Code silently serves nothing for a bad `localResourceRoots` path, so a
wrong media directory shows up as a blank chat panel with no error. These
assertions run in CI instead.
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXTENSION_JS = REPO / "extension" / "src" / "extension.js"


def test_every_media_path_in_extension_js_exists() -> None:
    source = EXTENSION_JS.read_text(encoding="utf-8")
    # Matches both joinPath(..., "extension", "media") and path.join equivalents.
    segments = re.findall(r'"((?:apps|extension))",\s*"(?:extension",\s*")?media"', source)
    assert segments, "no media directory reference found - did the layout change?"
    for first in set(segments):
        candidate = REPO / first / "media" if first == "extension" else REPO / first
        assert candidate.exists(), f"extension.js points at {candidate}, which does not exist"


def test_media_assets_referenced_by_name_are_present() -> None:
    media = REPO / "extension" / "media"
    for asset in ("chat.css", "chat.js", "dashboard.css", "dashboard.js", "chip.svg"):
        assert (media / asset).is_file(), f"missing webview asset: {asset}"


def test_package_json_main_points_at_a_real_file() -> None:
    manifest = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    main = (REPO / manifest["main"]).resolve()
    assert main.is_file(), f"package.json main -> {main} does not exist"


def test_activity_bar_icon_exists() -> None:
    manifest = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    for container in manifest["contributes"]["viewsContainers"].get("activitybar", []):
        icon = (REPO / container["icon"]).resolve()
        assert icon.is_file(), f"activity bar icon -> {icon} does not exist"
