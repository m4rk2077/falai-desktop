; Inno Setup script to build a Windows installer (setup.exe) for FALAI.
;
; How to use:
; 1) Build the app with PyInstaller so you have: dist\FALAI\FALAI.exe
; 2) Run ISCC.exe on this file:
;    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\FALAI.iss

#define MyAppName "FALAI"
#define MyAppVersion "1.5.6"
#define MyAppExeName "FALAI.exe"

[Setup]
AppId={{2E7B5E30-BCB1-4A6F-A6F0-0B6E2E0E3B67}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; Keep per-user install path stable to avoid side-by-side installs with old copies.
DefaultDirName={localappdata}\Programs\{#MyAppName}
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
; Include version in filename to avoid confusion when sharing installers.
OutputBaseFilename=FALAI-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icons\app.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Beta/testers: avoid needing admin rights. This also fixes the warning about per-user areas (userdesktop).
PrivilegesRequired=lowest
; Ensure updater can replace binaries even when app was left open.
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no
; "x64" is deprecated in newer Inno Setup; use x64compatible.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: checkedonce

[Files]
Source: "..\dist\FALAI\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
