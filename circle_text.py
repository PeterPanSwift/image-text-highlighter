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


def find_text_boxes(image_path, target, img_size, match_all=False):
    """找出 target 文字在圖片中的像素座標框 [(x0, y0, x1, y1), ...]"""
    W, H = img_size
    lines = ocr_lines(image_path)
    if not lines:
        sys.exit("錯誤: 圖片中偵測不到任何文字")

    target_n = normalize(target)
    boxes = []

    for raw, rec_text, obs in lines:
        # 建立「正規化字元 -> 原始字串索引」的對照表，才能精準取子字串範圍
        norm_chars, index_map = [], []
        for i, ch in enumerate(raw):
            for nch in normalize(ch):
                norm_chars.append(nch)
                index_map.append(i)
        line_n = "".join(norm_chars)

        start = 0
        while True:
            pos = line_n.find(target_n, start)
            if pos == -1:
                break
            lo = index_map[pos]
            hi = index_map[pos + len(target_n) - 1] + 1

            # 取得該子字串的精準邊界框（normalized 座標，原點在左下）
            rect_obs, _ = rec_text.boundingBoxForRange_error_(
                NSRange(lo, hi - lo), None
            )
            bb = rect_obs.boundingBox() if rect_obs else obs.boundingBox()
            x = bb.origin.x * W
            y = (1 - bb.origin.y - bb.size.height) * H
            w = bb.size.width * W
            h = bb.size.height * H
            boxes.append((x, y, x + w, y + h))
            if not match_all:
                return boxes
            start = pos + 1

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


def draw_glow_highlight(img, box, color=(64, 156, 255)):
    """在 box 周圍畫出發光的圓角圈選框（iOS glow highlight 風格）。"""
    W, H = img.size
    x0, y0, x1, y1 = box
    box_h = y1 - y0

    # 框往外留一點呼吸空間
    pad_x = max(10, box_h * 0.55)
    pad_y = max(8, box_h * 0.40)
    x0, y0 = max(2, x0 - pad_x), max(2, y0 - pad_y)
    x1, y1 = min(W - 2, x1 + pad_x), min(H - 2, y1 + pad_y)
    radius = min((y1 - y0) / 2, (x1 - x0) / 2)

    # 線寬與光暈大小依圖片尺寸縮放
    lw = max(3, round(min(W, H) * 0.006))
    glow_blur = lw * 2.2

    img = img.convert("RGBA")

    # 光暈層：畫粗的彩色框再高斯模糊，疊兩次讓光暈更亮
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(
        (x0, y0, x1, y1), radius=radius, outline=color + (255,), width=lw * 3
    )
    glow = glow.filter(ImageFilter.GaussianBlur(glow_blur))
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
    args = parser.parse_args()

    img = Image.open(args.image)
    boxes = find_text_boxes(args.image, args.text, img.size, match_all=args.all)

    color = hex_to_rgb(args.color)
    for box in boxes:
        img = draw_glow_highlight(img, box, color)

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
