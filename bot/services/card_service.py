from pathlib import Path

CARD_INFO_FILE = "card_info.txt"

_BASE_DIR = Path(__file__).resolve().parent.parent
_PRIMARY_CARD_FILE = _BASE_DIR / CARD_INFO_FILE
_LEGACY_CARD_FILES = [
    Path.cwd() / CARD_INFO_FILE,
    _BASE_DIR.parent / CARD_INFO_FILE,
]


def _read_card_file(path: Path) -> tuple[str, str] | None:
    if not path.exists():
        return None
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        number = lines[0] if len(lines) > 0 else ""
        holder = lines[1] if len(lines) > 1 else ""
        return number, holder
    except Exception:
        return None


def _write_card_file(path: Path, card_number: str, card_holder: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{(card_number or '').strip()}\n{(card_holder or '').strip()}\n", encoding="utf-8")


def get_card_info() -> tuple[str, str]:
    primary = _read_card_file(_PRIMARY_CARD_FILE)
    if primary is not None:
        return primary

    for legacy in _LEGACY_CARD_FILES:
        legacy_data = _read_card_file(legacy)
        if legacy_data is not None:
            _write_card_file(_PRIMARY_CARD_FILE, legacy_data[0], legacy_data[1])
            return legacy_data

    return "", ""


def set_card_info(card_number: str, card_holder: str = "") -> None:
    _write_card_file(_PRIMARY_CARD_FILE, card_number, card_holder)
