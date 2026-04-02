; ---------------------------------------
; BiliDanmakuSender - Inno Setup 配置文件
; ---------------------------------------

#ifndef AppVersion
#define AppVersion "Unknown"
#endif

#define AppName "BiliDanmakuSender"
#define AppExeName "BiliDanmakuSender.exe"
#define AppPublisher "Miku_oso"
#define AppSupportURL "https://touhougleaners.github.io/danmaku-sender/"
#define AppUpdatesURL "https://github.com/TouhouGleaners/danmaku-sender/releases"

[Setup]
AppId={{CD28BCC5-45C6-4824-8579-75A641BFABE3}

AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL={#AppSupportURL}
AppUpdatesURL={#AppUpdatesURL}

; 默认安装到当前用户的 Local Programs 目录
DefaultDirName={autopf}\{#AppPublisher}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

; 构建产物输出
OutputDir=Output
OutputBaseFilename={#AppName}-v{#AppVersion}-setup-x64
SetupIconFile=assets\icon.ico

; 最高压缩率
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "AppDist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "运行 {#AppName}"; Flags: nowait postinstall skipifsilent