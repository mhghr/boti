import json
from pathlib import Path

SOFTWARE_LINKS_FILE = "software_links.json"

DEFAULT_SOFTWARE_LINKS = {
    "ios": "https://apps.apple.com/us/app/wireguard/id1441195209",
    "android": "https://play.google.com/store/apps/details?id=com.wireguard.android&hl=en",
    "windows": "https://www.wireguard.com/install/",
}

_BASE_DIR = Path(__file__).resolve().parent.parent
_PRIMARY_LINKS_FILE = _BASE_DIR / SOFTWARE_LINKS_FILE
_LEGACY_LINKS_FILES = [
    Path.cwd() / SOFTWARE_LINKS_FILE,
    _BASE_DIR.parent / SOFTWARE_LINKS_FILE,
]


def _normalize_links(data: dict | None) -> dict[str, str]:
    data = data or {}
    return {
        "ios": str(data.get("ios") or DEFAULT_SOFTWARE_LINKS["ios"]).strip(),
        "android": str(data.get("android") or DEFAULT_SOFTWARE_LINKS["android"]).strip(),
        "windows": str(data.get("windows") or DEFAULT_SOFTWARE_LINKS["windows"]).strip(),
    }


def _read_links_file(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    try:
        return _normalize_links(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def _write_links_file(path: Path, links: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_normalize_links(links), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_software_links() -> dict[str, str]:
    primary = _read_links_file(_PRIMARY_LINKS_FILE)
    if primary is not None:
        return primary

    for legacy in _LEGACY_LINKS_FILES:
        legacy_data = _read_links_file(legacy)
        if legacy_data is not None:
            _write_links_file(_PRIMARY_LINKS_FILE, legacy_data)
            return legacy_data

    _write_links_file(_PRIMARY_LINKS_FILE, DEFAULT_SOFTWARE_LINKS)
    return DEFAULT_SOFTWARE_LINKS.copy()


def set_software_link(platform: str, url: str) -> dict[str, str]:
    links = get_software_links()
    links[platform] = (url or "").strip()
    _write_links_file(_PRIMARY_LINKS_FILE, links)
    return links
