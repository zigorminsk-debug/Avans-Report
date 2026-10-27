"""Версия приложения и параметры обновлений."""

from __future__ import annotations

# Версия подставляется автоматически в GitHub Actions из git-тега (v1.2.3 -> 1.2.3).
# При запуске из исходников значение ниже является версией по умолчанию.
__version__ = "1.0.9"

APP_NAME = "Авансовые отчёты"
APP_SLUG = "AvansReport"

# Репозиторий, из которого приложение проверяет и скачивает обновления.
GITHUB_REPO = "zigorminsk-debug/Avans-Report"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
