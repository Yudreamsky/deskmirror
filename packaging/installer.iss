; 桌面魔镜安装程序（Inno Setup 6）。不要直接编译：运行 python packaging\build.py --installer
; （先用 PyInstaller 打出 dist\DeskMirror，再用 ISCC 编译这个文件，版本号从 deskmirror\__init__.py 传进来）。
;
; 装在当前用户的 %LOCALAPPDATA%\Programs\DeskMirror：不用管理员权限，程序文件夹可以写，
; 魔镜自己的“检查更新”照样能直接换新版本（设置和日志也在这个文件夹里，和解压版一样）。
; 开机自启和程序里的设置写的是同一项（HKCU\…\Run 的 DeskMirror），两边改哪边都行。

#ifndef AppVersion
  #error 用 python packaging\build.py --installer 编译（要传 /DAppVersion=…）
#endif
#define AppExe "DeskMirror.exe"
#define SrcDir "..\dist\DeskMirror"

[Setup]
AppId={{5B7E0C1A-3D4F-4E8B-9A61-2C8F0D7E4B19}
AppName=DeskMirror
AppVerName=DeskMirror {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=Yudreamsky
AppPublisherURL=https://github.com/Yudreamsky/deskmirror
AppSupportURL=https://github.com/Yudreamsky/deskmirror/issues
AppUpdatesURL=https://github.com/Yudreamsky/deskmirror/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\DeskMirror
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
SetupIconFile=deskmirror.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName=DeskMirror
OutputDir=..\dist
OutputBaseFilename=DeskMirror-{#AppVersion}-win64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
; 正在运行的魔镜在 PrepareToInstall 里先请它自己退出；还有占着文件的（比如识别子进程）交给重启管理器
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "chinesetrad"; MessagesFile: "ChineseTraditional.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"

[CustomMessages]
AppTitle=DeskMirror
AutoStart=Start DeskMirror when I sign in to Windows
OtherTasks=Other:
DeleteData=Also delete your DeskMirror settings, usage logs and remembered translations?%n%n(Choose No to keep them for a later reinstall.)
chinesesimp.AppTitle=桌面魔镜
chinesesimp.AutoStart=登录 Windows 时自动启动桌面魔镜
chinesesimp.OtherTasks=其他：
chinesesimp.DeleteData=同时删除桌面魔镜的设置、用量日志和记住的译文吗？%n%n（选“否”会保留，以后重新安装还能接着用。）
chinesetrad.AppTitle=桌面魔鏡
chinesetrad.AutoStart=登入 Windows 時自動啟動桌面魔鏡
chinesetrad.OtherTasks=其他：
chinesetrad.DeleteData=同時刪除桌面魔鏡的設定、用量紀錄和記住的譯文嗎？%n%n（選「否」會保留，以後重新安裝還能接著用。）

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutoStart}"; GroupDescription: "{cm:OtherTasks}"; Flags: unchecked

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; 换版本时旧版本的 Python 运行库整个换掉，免得留下新版本不用的旧文件
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{cm:AppTitle}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{cm:AppTitle}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; 和程序里“开机自动启动”写的是同一项（deskmirror\autostart.py）；--autostart：开机时魔镜收成球待命
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DeskMirror"; \
    ValueData: """{app}\{#AppExe}"" --autostart"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{cm:AppTitle}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  EVENT_MODIFY_STATE = $0002;
  SYNCHRONIZE = $00100000;

function OpenEventW(Access: Cardinal; Inherit: BOOL; Name: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function SetEvent(Handle: THandle): BOOL;
  external 'SetEvent@kernel32.dll stdcall';
function OpenMutexW(Access: Cardinal; Inherit: BOOL; Name: String): THandle;
  external 'OpenMutexW@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

function AppRunning(): Boolean;
var
  H: THandle;
begin
  H := OpenMutexW(SYNCHRONIZE, False, 'Local\DeskMirror.Instance');
  Result := H <> 0;
  if Result then
    CloseHandle(H);
end;

{ 请正在运行的魔镜自己退出（和命令行更新用的是同一个事件），最多等 20 秒。返回它是不是已经退出了。 }
function CloseRunningApp(): Boolean;
var
  H: THandle;
  I: Integer;
begin
  Result := not AppRunning();
  if Result then
    exit;
  H := OpenEventW(EVENT_MODIFY_STATE, False, 'Local\DeskMirror.Quit');
  if H <> 0 then
  begin
    SetEvent(H);
    CloseHandle(H);
  end;
  for I := 1 to 80 do
  begin
    if not AppRunning() then
    begin
      Sleep(1500);          { 识别子进程跟着退出 }
      Result := True;
      exit;
    end;
    Sleep(250);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  CloseRunningApp();        { 关不掉的话 CloseApplications 会接着处理、提示用户 }
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  if not CloseRunningApp() then
  begin
    MsgBox(FmtMessage(SetupMessage(msgUninstallAppRunningError), [ExpandConstant('{cm:AppTitle}')]),
      mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Cmd: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    { 开机自启指向这次安装的话一起删掉（不管是安装时勾的还是后来在程序里打开的），免得开机报找不到文件 }
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DeskMirror', Cmd) and
       (Pos(Lowercase(ExpandConstant('{app}')), Lowercase(Cmd)) > 0) then
    begin
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'DeskMirror');
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run', 'DeskMirror');
    end;
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    { 程序文件删掉后，文件夹里剩下的是设置、日志、缓存：问一下要不要一起删 }
    { 静默卸载（比如脚本里）不问，保留 }
    if (not UninstallSilent) and DirExists(ExpandConstant('{app}')) and
       (MsgBox(ExpandConstant('{cm:DeleteData}'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(ExpandConstant('{app}'), True, True, True);
  end;
end;
