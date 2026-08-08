#!/usr/bin/env python3
"""
在圖片中找到指定文字，並加上漂亮的發光圈選效果。

用法:
    python3 circle_text.py 圖片.png "要標記的文字"
    python3 circle_text.py 圖片.png "要標記的文字" -o 輸出.png
    python3 circle_text.py 圖片.png "文字" --color "#FF5555"   # 換圈選顏色
    python3 circle_text.py 圖片.png "文字" --all               # 圈選所有出現的位置

使用 macOS 內建 Vision framework 做 OCR（支援中英文），
再用 Pillow 畫出帶光暈的圓角圈選框（參考 iOS 風格的 glow highlight）。
"""

import argparse
import sys
import unicodedata

import Quartz
import Vision
from Foundation import NSURL, NSRange
from PIL import Image, ImageDraw, ImageFilter


# ---------------------------------------------------------------- OCR ----

def ocr_lines(image_path):
    """回傳 [(文字, VNRecognizedText, VNRecognizedTextObservation), ...]"""
    url = NSURL.fileURLWithPath_(image_path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        sys.exit(f"錯誤: 無法讀取圖片 {image_path}")
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(["zh-Hant", "zh-Hans", "en-US"])
    request.setUsesLanguageCorrection_(True)

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cg_image, None
    )
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        sys.exit(f"錯誤: OCR 失敗 ({error})")

    lines = []
    for obs in request.results() or []:
        candidates = obs.topCandidates_(1)
        if candidates:
            text = candidates[0]
            lines.append((str(text.string()), text, obs))
    return lines


def normalize(s):
    """比對用正規化：全形轉半形、去空白、轉小寫。"""
    s = unicodedata.normalize("NFKC", s)
    return "".join(ch for ch in s.casefold() if not ch.isspace())


# OCR 常見的形近字混淆（單字元對單字元），比對時視為相同
CONFUSABLE_MAP = str.maketrans({
    "0": "o", "1": "l", "|": "l",
    "2": "z", "5": "s", "8": "b", "9": "g",
    "$": "s", "@": "a",
    "‘": "'", "’": "'", "‚": "'",  # ‘ ’ ‚
    "“": '"', "”": '"', "„": '"',  # “ ” „
})


def fold_confusables(s):
    """將形近字元折疊成同一代表字元（長度不變）。"""
    return s.translate(CONFUSABLE_MAP)


def find_in_line(line_n, target_n, fuzzy_threshold=0.8):
    """在正規化後的行文字中尋找目標，回傳 (start, end) 或 None。

    依序嘗試：完全比對 → 形近字折疊比對 → 近似比對（SequenceMatcher）。
    """
    pos = line_n.find(target_n)
    if pos != -1:
        return pos, pos + len(target_n)

    line_f, target_f = fold_confusables(line_n), fold_confusables(target_n)
    pos = line_f.find(target_f)
    if pos != -1:
        return pos, pos + len(target_f)

    # 近似比對：在行中滑動比較每個與目標等長（±2）的視窗
    from difflib import SequenceMatcher

    n, m = len(line_f), len(target_f)
    if m < 3 or n < m - 2:
        return None
    best_ratio, best_span = 0.0, None
    matcher = SequenceMatcher(b=target_f, autojunk=False)
    for width in (m, m + 1, m + 2, max(3, m - 1), max(3, m - 2)):
        for start in range(0, n - width + 1):
            matcher.set_seq1(line_f[start : start + width])
            if matcher.real_quick_ratio() < fuzzy_threshold:
                continue
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best_ratio, best_span = ratio, (start, start + width)
    if best_ratio >= fuzzy_threshold:
        return best_span
    return None


def _norm_with_map(raw):
    """回傳 (正規化字串, 每個正規化字元對應的原始字串索引)。"""
    norm_chars, index_map = [], []
    for i, ch in enumerate(raw):
        for nch in normalize(ch):
            norm_chars.append(nch)
            index_map.append(i)
    return "".join(norm_chars), index_map


def _range_box(rec_text, obs, lo, hi, W, H):
    """取得原始字串 [lo, hi) 範圍的像素座標框。"""
    rect_obs, _ = rec_text.boundingBoxForRange_error_(
        NSRange(lo, hi - lo), None
    )
    bb = rect_obs.boundingBox() if rect_obs else obs.boundingBox()
    x = bb.origin.x * W
    y = (1 - bb.origin.y - bb.size.height) * H
    return (x, y, x + bb.size.width * W, y + bb.size.height * H)


def _find_in_single_lines(lines, target_n, match_all, W, H):
    """逐一在每個 OCR 區塊內尋找目標。"""
    boxes = []
    for raw, rec_text, obs in lines:
        line_n, index_map = _norm_with_map(raw)

        # 先找所有完全符合的位置；整行都沒有時退而使用容錯比對（單一結果）
        spans = []
        start = 0
        while True:
            pos = line_n.find(target_n, start)
            if pos == -1:
                break
            spans.append((pos, pos + len(target_n)))
            start = pos + 1
        if not spans:
            span = find_in_line(line_n, target_n)
            if span:
                spans.append(span)

        for pos, end in spans:
            lo, hi = index_map[pos], index_map[end - 1] + 1
            boxes.append(_range_box(rec_text, obs, lo, hi, W, H))
            if not match_all:
                return boxes
    return boxes


def _group_rows(lines):
    """把垂直位置重疊的 OCR 區塊分組成「同一橫列」，列內由左至右排序。"""
    items = []
    for line in lines:
        bb = line[2].boundingBox()
        items.append(
            (bb.origin.x, bb.origin.y, bb.origin.y + bb.size.height, line)
        )
    items.sort(key=lambda it: -it[2])  # 由上而下（normalized y 越大越上面）

    rows = []
    for x, y0, y1, line in items:
        placed = False
        for row in rows:
            ry0, ry1 = row["y0"], row["y1"]
            overlap = min(y1, ry1) - max(y0, ry0)
            if overlap >= 0.5 * min(y1 - y0, ry1 - ry0):
                row["items"].append((x, line))
                row["y0"], row["y1"] = min(y0, ry0), max(y1, ry1)
                placed = True
                break
        if not placed:
            rows.append({"y0": y0, "y1": y1, "items": [(x, line)]})

    for row in rows:
        row["items"].sort(key=lambda it: it[0])
    return [[line for _, line in row["items"]] for row in rows]


def _find_across_row(row, target_n, W, H):
    """把同一橫列的多個 OCR 區塊串起來比對（如 UI 的「標籤 + 值」）。"""
    concat, seg_map = "", []  # seg_map: 每個字元對應 (區塊索引, 原始字元索引)
    for idx, (raw, _, _) in enumerate(row):
        line_n, index_map = _norm_with_map(raw)
        concat += line_n
        seg_map.extend((idx, j) for j in index_map)

    pos = concat.find(target_n)
    span = (pos, pos + len(target_n)) if pos != -1 else find_in_line(
        concat, target_n
    )
    if not span:
        return None

    # 找出匹配範圍涉及哪些區塊、各自的字元範圍，取邊界框聯集
    involved = {}
    for k in range(span[0], span[1]):
        idx, j = seg_map[k]
        lo, hi = involved.get(idx, (j, j))
        involved[idx] = (min(lo, j), max(hi, j))

    union = None
    for idx, (lo, hi) in involved.items():
        raw, rec_text, obs = row[idx]
        b = _range_box(rec_text, obs, lo, hi + 1, W, H)
        union = b if union is None else (
            min(union[0], b[0]), min(union[1], b[1]),
            max(union[2], b[2]), max(union[3], b[3]),
        )
    return union


def find_text_boxes(image_path, target, img_size, match_all=False):
    """找出 target 文字在圖片中的像素座標框 [(x0, y0, x1, y1), ...]"""
    W, H = img_size
    lines = ocr_lines(image_path)
    if not lines:
        sys.exit("錯誤: 圖片中偵測不到任何文字")

    target_n = normalize(target)

    # 第一輪：在單一 OCR 區塊內找
    boxes = _find_in_single_lines(lines, target_n, match_all, W, H)
    if boxes:
        return boxes

    # 第二輪：目標可能橫跨同一列的多個區塊（例如「Interface: SwiftUI」
    # 的標籤和選單值），把同列區塊串接後再找一次
    for row in _group_rows(lines):
        if len(row) < 2:
            continue
        box = _find_across_row(row, target_n, W, H)
        if box:
            boxes.append(box)
            if not match_all:
                return boxes
    if boxes:
        return boxes

    # 找不到時給提示
    print(f"錯誤: 在圖片中找不到「{target}」", file=sys.stderr)
    print("圖片中偵測到的文字有：", file=sys.stderr)
    for raw, _, _ in lines:
        print(f"  - {raw}", file=sys.stderr)
    sys.exit(1)


# ------------------------------------------------------------- 畫圈選 ----

def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def pad_box(img_size, box):
    """把文字框往外擴一點呼吸空間，回傳 (框, 圓角半徑)。"""
    W, H = img_size
    x0, y0, x1, y1 = box
    box_h = y1 - y0
    pad_x = max(10, box_h * 0.55)
    pad_y = max(8, box_h * 0.40)
    x0, y0 = max(2, x0 - pad_x), max(2, y0 - pad_y)
    x1, y1 = min(W - 2, x1 + pad_x), min(H - 2, y1 + pad_y)
    radius = min((y1 - y0) / 2, (x1 - x0) / 2)
    return (x0, y0, x1, y1), radius


def dim_background(img, padded_boxes, strength=0.35):
    """壓暗圈選框以外的區域，讓焦點落在圈選的文字上。"""
    W, H = img.size
    img = img.convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, round(255 * strength)))
    od = ImageDraw.Draw(overlay)
    for box, radius in padded_boxes:
        od.rounded_rectangle(box, radius=radius, fill=(0, 0, 0, 0))
    # 讓明暗交界柔和一點
    overlay = overlay.filter(
        ImageFilter.GaussianBlur(max(2, round(min(W, H) * 0.004)))
    )
    img.alpha_composite(overlay)
    return img


def draw_glow_highlight(img, padded_box, radius, color=(64, 156, 255)):
    """在框周圍畫出發光的圓角圈選框（iOS glow highlight 風格）。"""
    W, H = img.size
    x0, y0, x1, y1 = padded_box
    box_h = y1 - y0

    # 線寬同時參考框的高度與圖片尺寸：大圖裡圈小字時，
    # 若只按圖片尺寸縮放，粗線和光暈會不成比例地蓋住文字
    lw = max(2, round(min(box_h * 0.09, min(W, H) * 0.006)))
    glow_blur = lw * 2.2

    img = img.convert("RGBA")

    # 光暈層：畫粗的彩色框再高斯模糊，疊兩次讓光暈更亮；
    # 把框內部挖空，讓光只向外暈開、不染到圈選的文字
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(
        (x0, y0, x1, y1), radius=radius, outline=color + (255,), width=lw * 3
    )
    glow = glow.filter(ImageFilter.GaussianBlur(glow_blur))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(
        (x0 + lw, y0 + lw, x1 - lw, y1 - lw),
        radius=max(1, radius - lw),
        fill=(0, 0, 0, 0),
    )
    img.alpha_composite(glow)
    img.alpha_composite(glow)

    # 主框：飽和色
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.rounded_rectangle(
        (x0, y0, x1, y1), radius=radius, outline=color + (255,), width=lw
    )
    ring = ring.filter(ImageFilter.GaussianBlur(lw * 0.25))
    img.alpha_composite(ring)

    # 內圈亮線：接近白色，做出「發亮」的中心
    core_color = tuple(min(255, c + 170) for c in color)
    core = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    inset = lw * 0.35
    cd.rounded_rectangle(
        (x0 + inset, y0 + inset, x1 - inset, y1 - inset),
        radius=max(1, radius - inset),
        outline=core_color + (230,),
        width=max(2, round(lw * 0.5)),
    )
    core = core.filter(ImageFilter.GaussianBlur(lw * 0.2))
    img.alpha_composite(core)

    return img


# ---------------------------------------------------------------- main ----

def main():
    parser = argparse.ArgumentParser(
        description="在圖片中找到指定文字並加上發光圈選標記"
    )
    parser.add_argument("image", help="圖片路徑")
    parser.add_argument("text", help="要圈選的文字")
    parser.add_argument("-o", "--output", help="輸出路徑（預設: 原檔名_marked.png）")
    parser.add_argument(
        "--color", default="#409CFF", help="圈選顏色 hex（預設 #409CFF 藍色）"
    )
    parser.add_argument(
        "--all", action="store_true", help="圈選文字出現的所有位置（預設只圈第一個）"
    )
    parser.add_argument(
        "--dim",
        type=float,
        default=0.35,
        metavar="0~1",
        help="背景壓暗程度，0 為不壓暗（預設 0.35）",
    )
    args = parser.parse_args()

    img = Image.open(args.image)
    boxes = find_text_boxes(args.image, args.text, img.size, match_all=args.all)

    color = hex_to_rgb(args.color)
    padded = [pad_box(img.size, box) for box in boxes]
    if args.dim > 0:
        img = dim_background(img, padded, min(args.dim, 0.9))
    for box, radius in padded:
        img = draw_glow_highlight(img, box, radius, color)

    output = args.output
    if not output:
        stem = args.image.rsplit(".", 1)[0]
        output = f"{stem}_marked.png"
    img.convert("RGB").save(output) if output.lower().endswith(
        (".jpg", ".jpeg")
    ) else img.save(output)

    print(f"已圈選 {len(boxes)} 處「{args.text}」→ {output}")


if __name__ == "__main__":
    main()
