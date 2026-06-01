import json
from pathlib import Path

SOFTWARE_LINKS_FILE = "software_links.json"

DEFAULT_SOFTWARE_LIST = [
    {
        "name": "WireGuard",
        "ios": "https://apps.apple.com/us/app/wireguard/id1441195209",
        "android": "https://play.google.com/store/apps/details?id=com.wireguard.android&hl=en",
        "windows": "https://www.wireguard.com/install/",
    },
]

_BASE_DIR = Path(__file__).resolve().parent.parent
_PRIMARY_LINKS_FILE = _BASE_DIR / SOFTWARE_LINKS_FILE
_LEGACY_LINKS_FILES = [
    Path.cwd() / SOFTWARE_LINKS_FILE,
    _BASE_DIR.parent / SOFTWARE_LINKS_FILE,
]


def _normalize_entry(entry: dict) -> dict:
    return {
        "name": str(entry.get("name") or "").strip(),
        "ios": str(entry.get("ios") or "").strip(),
        "android": str(entry.get("android") or "").strip(),
        "windows": str(entry.get("windows") or "").strip(),
    }


def _migrate_legacy(raw: dict | list) -> list[dict]:
    if isinstance(raw, list):
        return [_normalize_entry(e) for e in raw if e.get("name")]
    if isinstance(raw, dict):
        name = str(raw.get("name") or "").strip() or "نرم‌افزار"
        return [_normalize_entry({"name": name, **raw})]
    return [dict(e) for e in DEFAULT_SOFTWARE_LIST]


def _read_links_file(path: Path) -> list[dict] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _migrate_legacy(raw)
    except Exception:
        return None


def _write_links_file(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_software_list() -> list[dict]:
    primary = _read_links_file(_PRIMARY_LINKS_FILE)
    if primary is not None:
        return primary
    for legacy in _LEGACY_LINKS_FILES:
        legacy_data = _read_links_file(legacy)
        if legacy_data is not None:
            _write_links_file(_PRIMARY_LINKS_FILE, legacy_data)
            return legacy_data
    default = [dict(e) for e in DEFAULT_SOFTWARE_LIST]
    _write_links_file(_PRIMARY_LINKS_FILE, default)
    return default


def add_software(name: str, ios: str = "", android: str = "", windows: str = "") -> list[dict]:
    data = get_software_list()
    data.append(_normalize_entry({"name": name, "ios": ios, "android": android, "windows": windows}))
    _write_links_file(_PRIMARY_LINKS_FILE, data)
    return data


def update_software_link(index: int, platform: str, url: str) -> list[dict]:
    data = get_software_list()
    if 0 <= index < len(data):
        data[index][platform] = (url or "").strip()
        data[index] = _normalize_entry(data[index])
        _write_links_file(_PRIMARY_LINKS_FILE, data)
    return data


def delete_software(index: int) -> list[dict]:
    data = get_software_list()
    if 0 <= index < len(data):
        data.pop(index)
        _write_links_file(_PRIMARY_LINKS_FILE, data)
    return data


# --- Backward compatibility wrappers (operate on first entry) ---

def get_software_links() -> dict[str, str]:
    data = get_software_list()
    if data:
        entry = data[0]
        return {"ios": entry["ios"], "android": entry["android"], "windows": entry["windows"]}
    return {"ios": "", "android": "", "windows": ""}


def set_software_link(platform: str, url: str) -> dict[str, str]:
    data = get_software_list()
    if not data:
        add_software("نرم‌افزار")
    else:
        update_software_link(0, platform, url)
    return get_software_links()
