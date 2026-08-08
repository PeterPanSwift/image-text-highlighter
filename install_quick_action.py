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
    if WORKFLOW_DIR.exists():
        shutil.rmtree(WORKFLOW_DIR)
        subprocess.run(
            ["/System/Library/CoreServices/pbs", "-update"], check=False
        )
        print(f"已移除: {WORKFLOW_DIR}")
    else:
        print("尚未安裝，無需移除")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove()
    else:
        install()
