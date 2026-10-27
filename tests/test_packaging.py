"""Проверки упаковки: пути к ресурсам, спецификация PyInstaller, установщик, CI."""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_resource_dir_in_frozen_mode(monkeypatch, tmp_path):
    from app import config

    bundle = tmp_path / "bundle"
    (bundle / "app" / "static").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert config.resource_dir() == bundle / "app"
    assert config.static_dir() == bundle / "app" / "static"
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert config.static_dir().name == "static"


def test_data_dir_outside_program_files(monkeypatch, tmp_path):
    from app import config

    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path / "custom"))
    assert config.data_dir() == tmp_path / "custom"
    assert config.data_dir().exists()
    assert config.db_path().name == "avans.db"


def test_pyinstaller_spec_is_valid():
    spec = ROOT / "desktop" / "AvansReport.spec"
    source = spec.read_text(encoding="utf-8")
    namespace = {"SPECPATH": str(spec.parent)}
    compile(source, str(spec), "exec")
    # Спецификация ссылается на существующие каталоги ресурсов
    assert (ROOT / "app" / "static" / "index.html").exists()
    assert (ROOT / "app" / "assets" / "template.xlsm").exists()
    assert (ROOT / "installer" / "windows" / "app.ico").exists()
    assert "launcher.py" in source
    assert "console=False" in source or "console=True" in source


def test_installer_files_exist():
    folder = ROOT / "installer" / "windows"
    for name in ("AvansReport.iss", "app.ico", "license.txt", "readme.txt"):
        assert (folder / name).exists(), name

    iss = (folder / "AvansReport.iss").read_text(encoding="utf-8")
    assert "APP_VERSION" in iss
    # База данных не должна удаляться при удалении программы
    assert "[UninstallDelete]" in iss
    assert "userappdata" in iss
    assert "netsh" in iss  # правило брандмауэра для режима сервера


def test_workflows_are_valid():
    workflows = ROOT / ".github" / "workflows"
    ci = yaml.safe_load((workflows / "ci.yml").read_text(encoding="utf-8"))
    release = yaml.safe_load((workflows / "release.yml").read_text(encoding="utf-8"))
    assert "jobs" in ci and "test" in ci["jobs"]
    assert "test" in release["jobs"]
    assert "windows" in release["jobs"]
    assert "publish" in release["jobs"]
    release_text = (workflows / "release.yml").read_text(encoding="utf-8")
    assert "AvansReport.iss" in release_text
    assert "pyinstaller" in release_text.lower()


def test_linux_installer_script():
    script = ROOT / "installer" / "linux" / "install-server.sh"
    text = script.read_text(encoding="utf-8")
    assert "systemd" in text or "systemctl" in text
    assert "AVANS_DATA_DIR" in text
    assert script.stat().st_mode & 0o111, "скрипт должен быть исполняемым"


def test_readme_documents_key_features():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for keyword in ("авансов", "установщик", "обновлен", "SQLite"):
        assert keyword.lower() in readme.lower()
