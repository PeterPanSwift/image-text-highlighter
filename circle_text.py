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
from PIL import Image, ImageChops, ImageDraw, ImageFilter


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
            boxes.append([_range_box(rec_text, obs, lo, hi, W, H)])
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

    segments = []
    for idx, (lo, hi) in involved.items():
        raw, rec_text, obs = row[idx]
        segments.append(_range_box(rec_text, obs, lo, hi + 1, W, H))
    return segments


def find_text_boxes(image_path, target, img_size, match_all=False):
    """找出 target 在圖片中的匹配位置。

    回傳「群組」列表：每個群組是一次匹配，內含一個或多個文字段的
    像素座標框（跨多個 OCR 區塊的匹配會有多個段）。
    """
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
        segments = _find_across_row(row, target_n, W, H)
        if segments:
            boxes.append(segments)
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


# ----------------------------------------------------------- 容器偵測 ----

def detect_container(rgb, box):
    """偵測文字背後的 UI 容器色塊（按鈕、選單、輸入框等）。

    從文字框旁取樣容器底色，往四周掃描顏色相近的連續區域。
    先用較寬的顏色容差，若擴張結果不合理（抓到整片背景，常見於
    容器底色與視窗背景對比很低的深色介面）就縮小容差重試。
    全部失敗時回傳 None，呼叫端應回退使用原本的文字框。
    """
    for tol in (16, 10, 6, 4):
        result = _detect_container_tol(rgb, box, tol)
        if result:
            return result
    return None


def _detect_container_tol(rgb, box, tol):
    W, H = rgb.size
    px = rgb.load()
    x0 = max(0, min(int(box[0]), W - 1))
    y0 = max(0, min(int(box[1]), H - 1))
    x1 = max(x0 + 1, min(int(box[2]), W - 1))
    y1 = max(y0 + 1, min(int(box[3]), H - 1))
    th = y1 - y0
    cy = (y0 + y1) // 2

    # 容器底色：在文字結尾右側取多點的中位數，避免採到字緣的反鋸齒像素
    samples = []
    for dx in (max(3, th // 6), max(5, th // 3), max(8, th // 2)):
        sx = min(W - 1, x1 + dx)
        samples.append(px[sx, cy])
    samples.sort(key=lambda c: c[0] + c[1] + c[2])
    fill = samples[len(samples) // 2]

    def match(p):
        return (
            abs(p[0] - fill[0]) <= tol
            and abs(p[1] - fill[1]) <= tol
            and abs(p[2] - fill[2]) <= tol
        )

    def col_frac(x, ya, yb):
        """x 這一直行在 [ya, yb] 間符合底色的比例。"""
        step = max(1, (yb - ya) // 24)
        pts = range(ya, yb + 1, step)
        return sum(match(px[x, y]) for y in pts) / max(1, len(pts))

    def row_frac(y, xa, xb):
        step = max(1, (xb - xa) // 60)
        pts = range(xa, xb + 1, step)
        return sum(match(px[x, y]) for x in pts) / max(1, len(pts))

    FR = 0.6

    def expand_h(start, direction, ya, yb):
        """水平擴張；容忍小段不符（如選單的 ⌄ 圖示）後繼續。"""
        pos = start
        max_gap = max(4, round(th * 1.2))
        while 0 <= pos + direction < W:
            if col_frac(pos + direction, ya, yb) >= FR:
                pos += direction
                continue
            jumped = False
            for g in range(2, max_gap):
                cand = pos + direction * g
                if not (0 <= cand < W):
                    break
                if col_frac(cand, ya, yb) >= FR:
                    pos = cand
                    jumped = True
                    break
            if not jumped:
                break
        return pos

    L = expand_h(x0, -1, y0, y1)
    R = expand_h(x1, +1, y0, y1)

    T, B = y0, y1
    while T - 1 >= 0 and row_frac(T - 1, L, R) >= FR:
        T -= 1
    while B + 1 < H and row_frac(B + 1, L, R) >= FR:
        B += 1

    # 合理性檢查：擴太多代表抓到的是大面積背景而不是控制項
    if (B - T) > th * 2.8 or (R - L) >= W * 0.95:
        return None
    return (float(L), float(T), float(R), float(B))


def union_boxes(boxes):
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


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
    pad_y = max(9, box_h * 0.45)
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


def _v_gradient(width, height, top_alpha, bottom_alpha):
    """由上而下的垂直漸層遮罩（L 模式）。"""
    height = max(2, height)
    col = Image.new("L", (1, height))
    for i in range(height):
        col.putpixel(
            (0, i),
            round(top_alpha + (bottom_alpha - top_alpha) * i / (height - 1)),
        )
    return col.resize((max(1, width), height))


def _paste_masked(img, layer_rgb, alpha_mask, pos):
    """把小圖層以指定透明度遮罩合成到大圖上。"""
    W, H = img.size
    full = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    full.paste(layer_rgb, pos, alpha_mask)
    img.alpha_composite(full)


def draw_bubble_highlight(img, padded_box, radius, color=(64, 156, 255)):
    """3D 玻璃泡泡效果：投影、內容微放大、立體光影、鏡面高光。"""
    W, H = img.size
    x0, y0, x1, y1 = (round(v) for v in padded_box)
    bw, bh = x1 - x0, y1 - y0
    radius = min(radius, bh / 2, bw / 2)
    lw = max(2, round(min(bh * 0.07, min(W, H) * 0.005)))

    img = img.convert("RGBA")

    # 圓角遮罩（泡泡形狀，重複使用）
    bubble_mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(bubble_mask).rounded_rectangle(
        (0, 0, bw - 1, bh - 1), radius=radius, fill=255
    )

    # 先取原始內容（要在畫陰影前取，避免拍到陰影）
    region = img.crop((x0, y0, x1, y1))

    # 1. 底部投影：讓泡泡浮起來
    off = max(3, round(bh * 0.12))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (x0, y0 + off, x1, y1 + off), radius=radius, fill=(0, 0, 0, 130)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(bh * 0.10))
    img.alpha_composite(shadow)

    # 2. 內容微放大：凸透鏡的放大感
    scale = 1.08
    ew, eh = round(bw * scale), round(bh * scale)
    enlarged = region.resize((ew, eh), Image.LANCZOS)
    cx, cy = (ew - bw) // 2, (eh - bh) // 2
    enlarged = enlarged.crop((cx, cy, cx + bw, cy + bh))
    img.paste(enlarged, (x0, y0), bubble_mask)

    # 3. 立體光影：上半透白光、下緣沉一點暗色
    light = Image.new("RGBA", (bw, bh), (255, 255, 255, 255))
    light_mask = ImageChops.multiply(
        _v_gradient(bw, bh, 55, 0), bubble_mask
    )
    _paste_masked(img, light, light_mask, (x0, y0))

    dark = Image.new("RGBA", (bw, bh), (0, 0, 25, 255))
    dark_mask = ImageChops.multiply(
        _v_gradient(bw, bh, 0, 40), bubble_mask
    )
    _paste_masked(img, dark, dark_mask, (x0, y0))

    # 4. 頂部鏡面高光：窄而亮的反光條，才有玻璃質感
    spec = Image.new("L", (bw, bh), 0)
    spec_top = max(2, round(bh * 0.07))
    spec_h = round(bh * 0.24)
    inset_x = max(4, round(bw * 0.05))
    ImageDraw.Draw(spec).rounded_rectangle(
        (inset_x, spec_top, bw - inset_x, spec_top + spec_h),
        radius=max(2, round(spec_h / 2)),
        fill=125,
    )
    spec = spec.filter(ImageFilter.GaussianBlur(bh * 0.03))
    spec = ImageChops.multiply(spec, bubble_mask)
    _paste_masked(img, Image.new("RGBA", (bw, bh), (255, 255, 255, 255)),
                  spec, (x0, y0))

    # 4b. 底部回光：玻璃下緣的細反射
    counter = Image.new("RGBA", (bw, bh), (255, 255, 255, 255))
    counter_mask = ImageChops.multiply(
        _v_gradient(bw, bh, 0, 45), bubble_mask
    )
    counter_band = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(counter_band).rectangle(
        (0, round(bh * 0.82), bw, bh), fill=255
    )
    counter_band = counter_band.filter(ImageFilter.GaussianBlur(bh * 0.05))
    counter_mask = ImageChops.multiply(counter_mask, counter_band)
    _paste_masked(img, counter, counter_mask, (x0, y0))

    # 5. 柔和外光暈（比 glow 樣式收斂）
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(
        (x0, y0, x1, y1), radius=radius, outline=color + (200,), width=lw * 2
    )
    glow = glow.filter(ImageFilter.GaussianBlur(lw * 1.8))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(
        (x0 + lw, y0 + lw, x1 - lw, y1 - lw),
        radius=max(1, radius - lw),
        fill=(0, 0, 0, 0),
    )
    img.alpha_composite(glow)

    # 6. 主框 + 頂部受光的白色邊緣（光源在上方的立體感）
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle(
        (x0, y0, x1, y1), radius=radius, outline=color + (255,), width=lw
    )
    ring = ring.filter(ImageFilter.GaussianBlur(lw * 0.2))
    img.alpha_composite(ring)

    rim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle(
        (x0, y0, x1, y1),
        radius=radius,
        outline=(255, 255, 255, 255),
        width=max(1, round(lw * 0.6)),
    )
    rim = rim.filter(ImageFilter.GaussianBlur(lw * 0.25))
    rim_grad = Image.new("L", (W, H), 0)
    rim_grad.paste(_v_gradient(bw, bh, 230, 0), (x0, y0))
    rim.putalpha(ImageChops.multiply(rim.getchannel("A"), rim_grad))
    img.alpha_composite(rim)

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
    parser.add_argument(
        "--style",
        choices=["bubble", "glow"],
        default="bubble",
        help="圈選樣式：bubble 立體玻璃泡泡（預設）/ glow 發光框",
    )
    parser.add_argument(
        "--no-container",
        action="store_true",
        help="停用容器偵測（預設會自動把圈選延伸到文字所在的按鈕/選單色塊）",
    )
    parser.add_argument(
        "--extend",
        default=None,
        metavar="R 或 L,T,R,B",
        help="手動延伸圈選框（像素）。單一數字只延伸右側，"
        "或以逗號給出 左,上,右,下 四個值",
    )
    args = parser.parse_args()

    extend = (0.0, 0.0, 0.0, 0.0)
    if args.extend:
        parts = [float(v) for v in args.extend.split(",")]
        if len(parts) == 1:
            extend = (0.0, 0.0, parts[0], 0.0)
        elif len(parts) == 4:
            extend = tuple(parts)
        else:
            sys.exit("錯誤: --extend 需要 1 個或 4 個數字（左,上,右,下）")

    img = Image.open(args.image)
    groups = find_text_boxes(
        args.image, args.text, img.size, match_all=args.all
    )

    # 每個文字段先嘗試延伸到其所在的 UI 容器色塊，再取聯集
    rgb = img.convert("RGB")
    boxes = []
    for segments in groups:
        if not args.no_container:
            segments = [
                detect_container(rgb, seg) or seg for seg in segments
            ]
        x0, y0, x1, y1 = union_boxes(segments)
        boxes.append(
            (x0 - extend[0], y0 - extend[1], x1 + extend[2], y1 + extend[3])
        )

    color = hex_to_rgb(args.color)
    padded = [pad_box(img.size, box) for box in boxes]
    if args.dim > 0:
        img = dim_background(img, padded, min(args.dim, 0.9))
    draw = draw_bubble_highlight if args.style == "bubble" else draw_glow_highlight
    for box, radius in padded:
        img = draw(img, box, radius, color)

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
