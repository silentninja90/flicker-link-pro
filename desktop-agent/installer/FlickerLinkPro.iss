[Setup]
AppId=FlickerLinkPro
AppName=Flicker Link Pro
AppVersion=2.2.0
AppPublisher=Eric Williams
VersionInfoCompany=Eric Williams
VersionInfoDescription=Flicker Link Pro Windows app
VersionInfoProductName=Flicker Link Pro
VersionInfoProductVersion=2.2.0
DefaultDirName={localappdata}\Programs\Flicker Link Pro
DefaultGroupName=Flicker Link Pro
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
UninstallDisplayIcon={app}\FlickerLinkPro.exe
OutputBaseFilename=FlickerLinkPro-Setup-x64
SetupIconFile={#BuildRoot}\flicker-link.ico
Compression=lzma2
SolidCompression=yes
SignTool=FlickerLinkProSign
SignedUninstaller=yes

[Files]
Source: "{#BuildRoot}\FlickerLinkPro\FlickerLinkPro.exe"; DestDir: "{app}"; Flags: ignoreversion signonce
Source: "{#BuildRoot}\FlickerLinkPro\*"; Excludes: "FlickerLinkPro.exe"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Flicker Link Pro"; Filename: "{app}\FlickerLinkPro.exe"; WorkingDir: "{app}"
Name: "{group}\Sign out of Flicker Link Pro"; Filename: "{app}\FlickerLinkPro.exe"; Parameters: "--logout"; WorkingDir: "{app}"
Name: "{autodesktop}\Flicker Link Pro"; Filename: "{app}\FlickerLinkPro.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\FlickerLinkPro.exe"; WorkingDir: "{app}"; Description: "Open Flicker Link Pro"; Flags: nowait postinstall skipifsilent
