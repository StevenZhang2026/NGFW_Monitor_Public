"""
Password strength validation.

- Minimum 8 characters
- Must contain: uppercase, lowercase, digit, special character
- Blocklist of common/breached passwords
- No username reuse
"""

import re
from pathlib import Path

_COMMON_PASSWORDS: set[str] | None = None

COMMON_PASSWORDS_FILE = Path(__file__).parent / "common_passwords.txt"

MIN_LENGTH = 8


def _load_common_passwords() -> set[str]:
    global _COMMON_PASSWORDS
    if _COMMON_PASSWORDS is not None:
        return _COMMON_PASSWORDS
    _COMMON_PASSWORDS = set()
    if COMMON_PASSWORDS_FILE.exists():
        with open(COMMON_PASSWORDS_FILE) as f:
            _COMMON_PASSWORDS = {line.strip().lower() for line in f if line.strip()}
    return _COMMON_PASSWORDS


def validate_password(password: str, role: str = "viewer", username: str = "") -> list[str]:
    """Validate password strength. Returns list of error messages (empty = valid)."""
    errors: list[str] = []

    if len(password) < MIN_LENGTH:
        errors.append(f"密码长度至少 {MIN_LENGTH} 位")

    if len(password) > 128:
        errors.append("密码长度不能超过 128 位")

    if not re.search(r"[a-z]", password):
        errors.append("必须包含小写字母")

    if not re.search(r"[A-Z]", password):
        errors.append("必须包含大写字母")

    if not re.search(r"\d", password):
        errors.append("必须包含数字")

    if not re.search(r"[^a-zA-Z0-9]", password):
        errors.append("必须包含特殊字符")

    if username and password.lower() == username.lower():
        errors.append("密码不能与用户名相同")

    common = _load_common_passwords()
    if common and password.lower() in common:
        errors.append("该密码过于常见，已出现在泄露密码库中，请更换")

    return errors


def password_strength_score(password: str) -> int:
    """Return 0-4 strength score for UI feedback."""
    if len(password) < MIN_LENGTH:
        return 0
    common = _load_common_passwords()
    if common and password.lower() in common:
        return 0
    score = 0
    has_lower = bool(re.search(r"[a-z]", password))
    has_upper = bool(re.search(r"[A-Z]", password))
    has_digit = bool(re.search(r"\d", password))
    has_special = bool(re.search(r"[^a-zA-Z0-9]", password))
    score += sum([has_lower, has_upper, has_digit, has_special])
    if len(password) >= 12:
        score = min(score + 1, 4)
    return min(score, 4)
