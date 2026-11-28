"""Lightweight image QC gate; catches corrupt, blank, tiny, and obvious artificial frames."""
from pathlib import Path
from PIL import Image, ImageStat


def inspect_image(path: Path, expected=(720, 1280)) -> list[str]:
    issues = []
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im = im.convert("RGB")
            if im.size != expected:
                issues.append(
                    f"ขนาดผิด {im.width}x{im.height} (คาด {expected[0]}x{expected[1]})"
                )

            small = im.resize((128, 228))
            stat = ImageStat.Stat(small)
            if sum(stat.stddev) / 3 < 5:
                issues.append("ภาพเกือบเป็นสีเดียว/อาจว่างเปล่า")

            # ตรวจกรอบขาวเฉพาะกรณีที่ขอบทั้งสี่ด้านเกือบขาวสม่ำเสมอ
            # และมีความต่างชัดเจนกับเนื้อหาด้านใน จึงไม่ปฏิเสธท้องฟ้า/กระดาษสีน้ำสว่าง
            px = im.resize((64, 114)).load()
            edge_pixels = []
            for x in range(64):
                edge_pixels.extend((px[x, 0], px[x, 113]))
            for y in range(1, 113):
                edge_pixels.extend((px[0, y], px[63, y]))

            bright_fraction = sum(
                1 for r, g, b in edge_pixels
                if min(r, g, b) > 242 and max(r, g, b) - min(r, g, b) < 8
            ) / len(edge_pixels)

            # Luminance spread on the edge; low spread means a nearly uniform frame.
            edge_luma = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in edge_pixels]
            edge_mean = sum(edge_luma) / len(edge_luma)
            edge_std = (sum((v - edge_mean) ** 2 for v in edge_luma) / len(edge_luma)) ** 0.5

            inner_pixels = [
                px[x, y]
                for y in range(3, 111)
                for x in range(3, 61)
            ]
            inner_luma = [
                0.2126 * r + 0.7152 * g + 0.0722 * b
                for r, g, b in inner_pixels
            ]
            inner_mean = sum(inner_luma) / len(inner_luma)

            if bright_fraction > 0.985 and edge_std < 3.5 and edge_mean - inner_mean > 18:
                issues.append("พบกรอบขาว/ครีมสม่ำเสมอรอบภาพ")
    except Exception as e:
        issues.append(f"เปิด/ถอดรหัสภาพไม่ได้: {type(e).__name__}: {e}")
    return issues
