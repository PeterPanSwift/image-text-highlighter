# image-text-highlighter

Find specified text in an image and highlight it with a beautiful glowing outline (iOS-style glow highlight).

Uses the built-in macOS Vision framework for OCR (supports English and Chinese), then draws a glowing rounded-rectangle highlight with Pillow.

[English](#english) | [中文說明](#中文說明)

## Demo

| English (default blue) | Chinese (custom red) |
| --- | --- |
| ![English demo](test_menu_marked.png) | ![Chinese demo](test_zh_marked.png) |

---

## English

### Requirements

- macOS (uses the system Vision framework for OCR)
- Python 3.9+

```bash
pip3 install Pillow pyobjc-framework-Vision
```

### Usage

```bash
python3 circle_text.py image.png "text to highlight"
```

### Options

| Option | Description |
| --- | --- |
| `-o output.png` | Output path (default: `<original name>_marked.png`) |
| `--color "#FF3B30"` | Highlight color in hex (default: iOS blue `#409CFF`) |
| `--all` | Highlight every occurrence of the text (default: first match only) |

### Examples

```bash
# Basic usage
python3 circle_text.py screenshot.png "Add files or photos"

# Red highlight with a custom output filename
python3 circle_text.py test_zh.png "圈選文字" --color "#FF3B30" -o result.png

# Highlight all occurrences
python3 circle_text.py doc.png "keyword" --all
```

### Features

- **Precise substring locating**: gets an accurate bounding box even when the target is only part of a line
- **Fuzzy matching**: ignores case, whitespace, and full-width/half-width differences
- **Auto scaling**: line width, glow size, and padding adapt to the image size — works for large screenshots and small images alike
- **Helpful errors**: when the text isn't found, all text detected in the image is listed so you can adjust your keyword

### Finder integration (opens result in Preview)

Preview itself doesn't support plugins, but you can get one-click integration in Finder:

```bash
python3 install_quick_action.py
```

This installs two entry points (both prompt for the text in a dialog, then open the marked image in Preview; if the text isn't found, an alert lists all text detected in the image):

1. **Open With app** (reliable): right-click any image → **Open With** → **圈選文字**. You can also drag images onto `~/Applications/圈選文字.app`.
2. **Quick Action**: right-click any image → **Quick Actions** → **圈選文字**. Note: hand-installed Quick Actions can be flaky on recent macOS — if it doesn't show up, use the Open With app instead.

To uninstall both:

```bash
python3 install_quick_action.py --remove
```

---

## 中文說明

在圖片中找到指定文字，並加上漂亮的發光圈選效果（iOS 風格 glow highlight）。

使用 macOS 內建 Vision framework 做 OCR（支援中英文），再用 Pillow 畫出帶光暈的圓角圈選框。

### 需求

- macOS（使用系統內建的 Vision framework 做 OCR）
- Python 3.9+

```bash
pip3 install Pillow pyobjc-framework-Vision
```

### 用法

```bash
python3 circle_text.py 圖片.png "要標記的文字"
```

### 選項

| 選項 | 說明 |
| --- | --- |
| `-o 輸出.png` | 指定輸出路徑（預設為 `原檔名_marked.png`） |
| `--color "#FF3B30"` | 圈選顏色，hex 格式（預設 iOS 藍 `#409CFF`） |
| `--all` | 圈選文字出現的所有位置（預設只圈第一個） |

### 範例

```bash
# 基本用法
python3 circle_text.py screenshot.png "Add files or photos"

# 紅色圈選 + 指定輸出檔名
python3 circle_text.py test_zh.png "圈選文字" --color "#FF3B30" -o result.png

# 圈選所有出現的位置
python3 circle_text.py doc.png "重點" --all
```

### 特色

- **精準子字串定位**：即使目標文字只是某一行的一部分，也會取得精確的邊界框
- **模糊比對**：自動忽略大小寫、空白、全形半形差異
- **自動縮放**：線寬、光暈大小、留白依圖片尺寸調整，大截圖和小圖都適用
- **友善錯誤提示**：找不到文字時，會列出圖片中實際偵測到的所有文字，方便調整關鍵字

### Finder 整合（結果自動用「預覽程式」打開）

「預覽程式」本身不支援外掛，但可以在 Finder 達成一鍵整合：

```bash
python3 install_quick_action.py
```

會同時安裝兩種入口（都會跳出對話框詢問要圈選的文字，完成後自動用「預覽程式」打開結果；找不到文字時會列出圖片中偵測到的所有文字）：

1. **打開檔案的應用程式**（推薦，穩定）：對圖片按右鍵 → **打開檔案的應用程式** → **圈選文字**，也可以直接把圖片拖到 `~/Applications/圈選文字.app` 上
2. **快速動作**：對圖片按右鍵 → **快速動作** → **圈選文字**。注意：手動安裝的快速動作在新版 macOS 上偶爾會從選單消失，遇到時請改用方式 1

移除方式（兩者一併移除）：

```bash
python3 install_quick_action.py --remove
```
