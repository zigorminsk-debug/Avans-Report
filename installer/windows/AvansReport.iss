; Скрипт установщика Windows (Inno Setup 6)
; Сборка выполняется в GitHub Actions: см. .github/workflows/release.yml

#define MyAppName "Авансовые отчёты"
#define MyAppVersion GetEnv("APP_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "ООО «Сэйлз Модерн групп»"
#define MyAppExeName "AvansReport.exe"
#define MyAppUrl "https://github.com/zigorminsk-debug/Avans-Report"
#define DataPort "8770"

[Setup]
AppId={{7C4B1E92-5F1D-4A63-9B7E-2E4C7A1D8F30}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}/issues
AppUpdatesURL={#MyAppUrl}/releases
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\AvansReport
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=AvansReport-Setup-{#MyAppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no
DisableWelcomePage=no
LicenseFile=license.txt
InfoBeforeFile=readme.txt
; База данных лежит в профиле пользователя и НЕ удаляется при удалении программы.

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "autostart"; Description: "Запускать программу при входе в Windows (режим сервера)"; GroupDescription: "Дополнительно:"; Flags: unchecked
Name: "firewall"; Description: "Разрешить доступ с других компьютеров локальной сети (порт {#DataPort})"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "..\..\dist\AvansReport\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Авансовые отчёты"
Name: "{group}\Каталог данных (база, резервные копии)"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--open-data-dir"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AvansReport"; ValueData: """{app}\{#MyAppExeName}"" --no-browser"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""AvansReport {#DataPort}"" dir=in action=allow protocol=TCP localport={#DataPort}"; Flags: runhidden; Tasks: firewall; StatusMsg: "Настройка брандмауэра…"
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Parameters: "--open-data-dir"; Description: "Открыть каталог с базой данных"; Flags: postinstall shellexec unchecked

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""AvansReport {#DataPort}"""; Flags: runhidden; RunOnceId: "DelFirewallRule"

[UninstallDelete]
; Удаляются только файлы, установленные программой.
; Каталог данных (%APPDATA%\AvansReport) сохраняется — там база и резервные копии.

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('Программа удалена.' + #13#10 + #13#10 +
           'База данных и резервные копии сохранены в каталоге:' + #13#10 +
           ExpandConstant('{userappdata}\AvansReport') + #13#10 + #13#10 +
           'Если они больше не нужны, удалите этот каталог вручную.',
           mbInformation, MB_OK);
  end;
end;
