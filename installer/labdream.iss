; Inno Setup script for LabDream Version 1.0
; Build after PyInstaller:  iscc installer\labdream.iss
; Output: installer\Output\LabDream_Setup_1.0.exe

#define AppName "LabDream"
#define AppVersion "1.0"
#define AppFullName "LabDream Version 1.0"
#define AppExe "LabDream.exe"

[Setup]
AppId={{6B0E5A52-3C1F-4B7A-9E2D-7A1C4F0B9D10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppFullName}
AppPublisher=LabDream
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=LabDream_Setup_{#AppVersion}
SetupIconFile=..\assets\labdream.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppFullName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes
VersionInfoVersion=1.0.0.0
VersionInfoProductName={#AppName}
VersionInfoProductVersion=1.0.0.0
VersionInfoProductTextVersion={#AppFullName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "assoc"; Description: "Open .ldd data files with LabDream"; GroupDescription: "File types:"

[Files]
Source: "..\dist\LabDream\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.ldd"; ValueType: string; ValueName: ""; ValueData: "LabDream.Data"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\LabDream.Data"; ValueType: string; ValueName: ""; ValueData: "LabDream data file"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\LabDream.Data\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\LabDream.Data\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
