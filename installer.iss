; Script Inno Setup pour Organisateur
; -----------------------------------------------------------------
; Pour compiler :
;   1. Installer Inno Setup depuis https://jrsoftware.org/isinfo.php
;   2. Ouvrir ce fichier avec Inno Setup Compiler
;   3. Build > Compile (F9)
;   4. L'installeur sera genere dans dist_installer\OrganisateurSetup.exe
; -----------------------------------------------------------------

#define MyAppName "Organisateur"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Pierre"
#define MyAppExeName "Organisateur.exe"

[Setup]
AppId={{C7B2F8E0-4F5D-4A2C-9B8E-7D6F3E2A1B5F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist_installer
OutputBaseFilename=OrganisateurSetup
SetupIconFile=
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Creer une icone sur le {cm:CreateDesktopIcon,Bureau}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Tout le dossier dist\Organisateur (compile par PyInstaller --onedir)
Source: "dist\Organisateur\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
