#!/usr/bin/env python3
"""
安裝「圈選文字」快速動作（Quick Action）到 macOS。

安裝後，在 Finder 對任何圖片按右鍵 → 快速動作 → 圈選文字，
輸入要圈選的文字後會自動執行 circle_text.py，並用「預覽程式」打開結果。

用法:
    python3 install_quick_action.py            # 安裝
    python3 install_quick_action.py --remove   # 移除
"""

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "圈選文字"
WORKFLOW_DIR = (
    Path.home() / "Library" / "Services" / f"{SERVICE_NAME}.workflow"
)
CIRCLE_TEXT = Path(__file__).resolve().parent / "circle_text.py"


def build_shell_script(python_path, script_path):
    """Quick Action 內執行的 zsh 腳本。"""
    return f'''PY={python_path!r}
SCRIPT={script_path!r}

for f in "$@"; do
  name=$(basename "$f")
  text=$(osascript - "$name" <<'APPLESCRIPT'
on run argv
  text returned of (display dialog "要在「" & (item 1 of argv) & "」中圈選的文字：" default answer "" with title "圈選文字" with icon note)
end run
APPLESCRIPT
  ) || continue
  [ -z "$text" ] && continue

  out="${{f%.*}}_marked.png"
  err=$("$PY" "$SCRIPT" "$f" "$text" -o "$out" 2>&1 >/dev/null)
  if [ $? -eq 0 ]; then
    open -a Preview "$out"
  else
    osascript - "$err" <<'APPLESCRIPT'
on run argv
  display alert "圈選失敗" message (item 1 of argv) as warning
end run
APPLESCRIPT
  fi
done
'''


BUNDLE_ID = f"com.apple.Automator.{SERVICE_NAME}"


def build_info_plist():
    return {
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": SERVICE_NAME,
        "NSServices": [
            {
                "NSBackgroundColorName": "background",
                "NSIconName": "NSActionTemplate",
                "NSMenuItem": {"default": SERVICE_NAME},
                "NSMessage": "runWorkflowAsService",
                "NSSendFileTypes": ["public.image"],
            }
        ],
    }


def build_document_wflow(shell_script):
    return {
        "AMApplicationBuild": "523",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [
            {
                "action": {
                    "AMAccepts": {
                        "Container": "List",
                        "Optional": True,
                        "Types": ["com.apple.cocoa.path"],
                    },
                    "AMActionVersion": "2.0.3",
                    "AMApplication": ["Automator"],
                    "AMParameterProperties": {
                        "COMMAND_STRING": {},
                        "CheckedForUserDefaultShell": {},
                        "inputMethod": {},
                        "shell": {},
                        "source": {},
                    },
                    "AMProvides": {
                        "Container": "List",
                        "Types": ["com.apple.cocoa.string"],
                    },
                    "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
                    "ActionName": "Run Shell Script",
                    "ActionParameters": {
                        "COMMAND_STRING": shell_script,
                        "CheckedForUserDefaultShell": True,
                        "inputMethod": 1,  # 以引數傳入
                        "shell": "/bin/zsh",
                        "source": "",
                    },
                    "BundleIdentifier": "com.apple.RunShellScript",
                    "CFBundleVersion": "2.0.3",
                    "CanShowSelectedItemsWhenRun": False,
                    "CanShowWhenRun": True,
                    "Category": ["AMCategoryUtilities"],
                    "Class Name": "RunShellScriptAction",
                    "InputUUID": "8A2C5E6B-0001-4E1A-9C3D-000000000001",
                    "Keywords": ["Shell", "Script"],
                    "OutputUUID": "8A2C5E6B-0002-4E1A-9C3D-000000000002",
                    "UUID": "8A2C5E6B-0003-4E1A-9C3D-000000000003",
                    "location": "309.000000:305.000000",
                    "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib",
                },
                "isViewVisible": 1,
            }
        ],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject.image",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 11,
            "processesInput": 0,
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject.image",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": 0,
            "systemImageName": "NSActionTemplate",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


APP_DIR = Path.home() / "Applications" / f"{SERVICE_NAME}.app"


def build_applescript(python_path):
    """「圈選文字.app」droplet 的 AppleScript 原始碼。

    circle_text.py 隨附在 App 的 Resources 內（安裝時複製），
    執行時以 path to me 取得，避免依賴受 TCC 保護的「文件」資料夾。
    """
    import shlex

    py = shlex.quote(python_path)
    # do shell script 使用 /bin/sh；${f%.*} 為 POSIX 語法可用
    shell_cmd = (
        'f=" & quoted form of p & "; '
        'out=\\"${f%.*}_marked.png\\"; '
        '__PY__ " & quoted form of scriptPath & " \\"$f\\" '
        '" & quoted form of t & " --style " & styleChoice & " '
        '--color " & quoted form of hexColor & " '
        '-o \\"$out\\" '
        '>/dev/null && /usr/bin/open -a Preview \\"$out\\"'
    ).replace("__PY__", py)
    template = '''on run
    display dialog "使用方式：在 Finder 對圖片按右鍵 → 打開檔案的應用程式 → 圈選文字，或直接把圖片拖到這個 App 圖示上。" buttons {"好"} default button 1 with title "圈選文字"
end run

on chooseStyle()
    set styleChoices to {"立體玻璃泡泡（預設）", "發光框", "手繪蠟筆"}
    set picked to choose from list styleChoices with title "圈選文字" with prompt "選擇圈選樣式：" default items {"立體玻璃泡泡（預設）"}
    if picked is false then return missing value
    set choice to item 1 of picked
    if choice is "發光框" then return "glow"
    if choice is "手繪蠟筆" then return "crayon"
    return "bubble"
end chooseStyle

on chooseHexColor()
    set colorChoices to {"藍色（預設）", "紅色", "橘色", "綠色", "紫色", "粉紅色", "自訂顏色…"}
    set picked to choose from list colorChoices with title "圈選文字" with prompt "選擇圈選顏色：" default items {"藍色（預設）"}
    if picked is false then return missing value
    set choice to item 1 of picked
    if choice is "紅色" then return "#FF3B30"
    if choice is "橘色" then return "#FF9500"
    if choice is "綠色" then return "#34C759"
    if choice is "紫色" then return "#AF52DE"
    if choice is "粉紅色" then return "#FF2D55"
    if choice is "自訂顏色…" then
        try
            set rgb to choose color default color {16448, 40092, 65535}
        on error
            return missing value
        end try
        return do shell script "printf '#%02X%02X%02X' " & ((item 1 of rgb) div 257) & " " & ((item 2 of rgb) div 257) & " " & ((item 3 of rgb) div 257)
    end if
    return "#409CFF"
end chooseHexColor

on open theFiles
    set scriptPath to POSIX path of (path to me) & "Contents/Resources/circle_text.py"
    repeat with f in theFiles
        set p to POSIX path of f
        set fileName to do shell script "basename " & quoted form of p
        try
            set dlg to display dialog "要在「" & fileName & "」中圈選的文字：" default answer "" with title "圈選文字" with icon note
            set t to text returned of dlg
        on error
            return
        end try
        if t is not "" then
            set styleChoice to chooseStyle()
            if styleChoice is missing value then return
            set hexColor to chooseHexColor()
            if hexColor is missing value then return
            try
                do shell script "__SHELL_CMD__"
            on error errMsg
                display alert "圈選失敗" message errMsg as warning
            end try
        end if
    end repeat
end open
'''
    return template.replace("__SHELL_CMD__", shell_cmd)


def install_open_with_app(python_path):
    """編譯 AppleScript droplet 並註冊為圖片的「打開檔案的應用程式」選項。"""
    import tempfile

    APP_DIR.parent.mkdir(parents=True, exist_ok=True)
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)

    source = build_applescript(python_path)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".applescript", delete=False
    ) as tmp:
        tmp.write(source)
        tmp_path = tmp.name
    try:
        subprocess.run(
            ["osacompile", "-o", str(APP_DIR), tmp_path], check=True
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # 將 circle_text.py 複製進 App，避免執行時得存取受保護的資料夾
    shutil.copy2(CIRCLE_TEXT, APP_DIR / "Contents" / "Resources")

    # 宣告可開啟圖片檔，讓它出現在「打開檔案的應用程式」選單
    info_path = APP_DIR / "Contents" / "Info.plist"
    with open(info_path, "rb") as f:
        info = plistlib.load(f)
    info["CFBundleIdentifier"] = "com.vibecoding.circle-text"
    info["CFBundleDisplayName"] = SERVICE_NAME
    info["CFBundleName"] = SERVICE_NAME
    info["CFBundleDocumentTypes"] = [
        {
            "CFBundleTypeName": "Image",
            "CFBundleTypeRole": "Viewer",
            "LSItemContentTypes": ["public.image"],
            "LSHandlerRank": "Alternate",
        }
    ]
    with open(info_path, "wb") as f:
        plistlib.dump(info, f)

    # 修改過 Info.plist / Resources 之後必須重新簽章，
    # 否則簽章失效，macOS 會直接拒絕檔案存取且不顯示權限詢問
    subprocess.run(
        ["codesign", "--force", "--sign", "-", str(APP_DIR)], check=True
    )

    # 清掉舊的（可能已被拒絕的）權限記錄，讓詢問視窗能重新出現
    for service in ("SystemPolicyDocumentsFolder", "SystemPolicyDesktopFolder",
                    "SystemPolicyDownloadsFolder"):
        subprocess.run(
            ["tccutil", "reset", service, "com.vibecoding.circle-text"],
            check=False, capture_output=True,
        )

    lsregister = (
        "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
        "LaunchServices.framework/Support/lsregister"
    )
    subprocess.run([lsregister, "-f", str(APP_DIR)], check=False)
    print(f"已安裝: {APP_DIR}")
    print("使用方式: 對圖片按右鍵 → 打開檔案的應用程式 → 圈選文字")


def install():
    if not CIRCLE_TEXT.exists():
        sys.exit(f"錯誤: 找不到 {CIRCLE_TEXT}")

    # 確認目前的 Python 有需要的套件
    try:
        import PIL  # noqa: F401
        import Vision  # noqa: F401
    except ImportError as e:
        sys.exit(
            f"錯誤: 目前的 Python（{sys.executable}）缺少套件 {e.name}。\n"
            "請先執行: pip3 install Pillow pyobjc-framework-Vision，"
            "再用同一個 python3 執行本安裝程式。"
        )

    contents = WORKFLOW_DIR / "Contents"
    if WORKFLOW_DIR.exists():
        shutil.rmtree(WORKFLOW_DIR)
    contents.mkdir(parents=True)

    shell_script = build_shell_script(sys.executable, str(CIRCLE_TEXT))
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump(build_info_plist(), f)
    with open(contents / "document.wflow", "wb") as f:
        plistlib.dump(build_document_wflow(shell_script), f)

    # 請系統重新掃描 Services
    subprocess.run(
        ["/System/Library/CoreServices/pbs", "-flush"], check=False
    )
    subprocess.run(
        ["/System/Library/CoreServices/pbs", "-update"], check=False
    )

    # 手動安裝的快速動作預設是停用的，直接在 pbs 偏好設定中啟用
    enable_service()

    subprocess.run(
        ["/System/Library/CoreServices/pbs", "-update"], check=False
    )
    subprocess.run(["killall", "Finder"], check=False)

    print(f"已安裝: {WORKFLOW_DIR}")
    print("使用方式: 在 Finder 對圖片按右鍵 → 快速動作 → 圈選文字")

    # 快速動作在部分系統上會不穩定，同時安裝「打開檔案的應用程式」版本
    install_open_with_app(sys.executable)


def enable_service():
    """在 pbs 偏好設定中啟用本服務（等同於在系統設定的延伸功能中勾選）。

    注意: key 以 "(null)" 開頭會讓 defaults write 解析失敗，
    因此改用 export → 修改 → import 的方式。
    """
    import tempfile

    keys = [
        f"{BUNDLE_ID} - {SERVICE_NAME} - runWorkflowAsService",
        f"(null) - {SERVICE_NAME} - runWorkflowAsService",
    ]
    with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run(
            ["defaults", "export", "pbs", tmp_path], check=True
        )
        with open(tmp_path, "rb") as f:
            prefs = plistlib.load(f)
        status = prefs.setdefault("NSServicesStatus", {})
        for key in keys:
            status[key] = {
                "enabled_context_menu": True,
                "enabled_services_menu": True,
                "presentation_modes": {
                    "ContextMenu": True,
                    "ServicesMenu": True,
                },
            }
        with open(tmp_path, "wb") as f:
            plistlib.dump(prefs, f)
        subprocess.run(
            ["defaults", "import", "pbs", tmp_path], check=True
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def remove():
    removed = False
    if WORKFLOW_DIR.exists():
        shutil.rmtree(WORKFLOW_DIR)
        subprocess.run(
            ["/System/Library/CoreServices/pbs", "-update"], check=False
        )
        print(f"已移除: {WORKFLOW_DIR}")
        removed = True
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
        print(f"已移除: {APP_DIR}")
        removed = True
    if not removed:
        print("尚未安裝，無需移除")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove()
    else:
        install()
