; Установщик автономной версии (Inno Setup 6)
; Сборка выполняется в GitHub Actions: см. .github/workflows/release.yml
;
; Автономная версия не требует сервера, базы данных и входа в систему:
; пользователь запускает программу и сразу заполняет отчёт.

#define MyAppName "Авансовые отчёты — автономный режим"
#define MyAppShortName "Авансовые отчёты (автономно)"
#define MyAppVersion GetEnv("APP_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "1.0.2"
#endif
#define MyAppPublisher "ООО «Сэйлз Модерн групп»"
#define MyAppExeName "AvansStandalone.exe"
#define MyAppUrl "https://github.com/zigorminsk-debug/Avans-Report"

[Setup]
; Отдельный AppId: автономную и серверную версии можно ставить рядом.
AppId={{3B8D5A17-6C42-49E8-A1F7-B5D2C90E4A61}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}/issues
AppUpdatesURL={#MyAppUrl}/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription=Автономная версия: заполнение, сохранение в PDF, печать
DefaultGroupName={#MyAppShortName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=AvansStandalone-Setup-{#MyAppVersion}
SetupIconFile=standalone.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Установка для текущего пользователя: не нужны права администратора,
; данные и отчёты хранятся в профиле пользователя и доступны на запись
; без запросов UAC.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\AvansStandalone
CloseApplications=yes
RestartApplications=no
DisableWelcomePage=no
LicenseFile=license.txt
InfoBeforeFile=standalone-readme.txt

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
Source: "..\..\dist\AvansStandalone\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; Автономная версия ставит только ярлык программы: отдельного ярлыка
; «Каталог отчётов» нет — папку с отчётами открывает кнопка «Открыть папку»
; в самой программе.
Name: "{group}\{#MyAppShortName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Заполнить и распечатать авансовый отчёт"
Name: "{group}\Удалить {#MyAppShortName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppShortName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Первый запуск открывает браузер с формой отчёта.
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppShortName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Удаляются только файлы программы.
; Сохранённые отчёты (%LOCALAPPDATA%\AvansReportStandalone) остаются на месте.

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('Программа удалена.' + #13#10 + #13#10 +
           'Сохранённые отчёты (PDF и файлы данных) остались в папке:' + #13#10 +
           ExpandConstant('{localappdata}\AvansReportStandalone') + #13#10 + #13#10 +
           'Удалите её вручную, если отчёты больше не нужны.',
           mbInformation, MB_OK);
  end;
end;
