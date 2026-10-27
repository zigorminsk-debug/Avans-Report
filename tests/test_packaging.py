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


def _spec_excludes(path: Path) -> str:
    import re

    text = path.read_text(encoding="utf-8")
    match = re.search(r"excludes=\[(.*?)\]", text, re.S)
    assert match, f"в {path.name} нет списка excludes"
    return match.group(1)


def test_specs_do_not_exclude_pdf_dependencies():
    """reportlab тянет PIL; fastapi и pydantic нужны самому приложению."""
    for name in ("AvansReport.spec", "AvansStandalone.spec"):
        excludes = _spec_excludes(ROOT / "desktop" / name)
        for module in ('"PIL"', '"reportlab"', '"fastapi"', '"pydantic"'):
            assert module not in excludes, f"{name}: нельзя исключать {module}"


def test_installer_setup_sections_have_no_duplicates():
    """Inno Setup падает на повторной директиве в [Setup]."""
    for name in ("AvansReport.iss", "AvansStandalone.iss"):
        path = ROOT / "installer" / "windows" / name
        section = None
        seen = set()
        duplicates = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped
                continue
            if section != "[Setup]" or not stripped or stripped.startswith((";", "#")):
                continue
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in seen:
                    duplicates.append(key)
                seen.add(key)
        assert not duplicates, f"{name}: повторные директивы {duplicates}"


def test_standalone_spec_collects_needed_data():
    spec = (ROOT / "desktop" / "AvansStandalone.spec").read_text(encoding="utf-8")
    for part in ("standalone", "static", "assets", "fonts", "uvicorn"):
        assert part in spec, f"в спецификации нет {part}"
    assert '"fastapi"' not in _spec_excludes(ROOT / "desktop" / "AvansStandalone.spec")
