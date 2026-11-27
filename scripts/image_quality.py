"""Lightweight image QC gate; catches corrupt, blank, tiny, and obvious edge-framing failures."""
from pathlib import Path
from PIL import Image, ImageStat

def inspect_image(path: Path, expected=(720,1280)) -> list[str]:
    issues=[]
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im=im.convert("RGB")
            if im.size != expected: issues.append(f"ขนาดผิด {im.width}x{im.height} (คาด {expected[0]}x{expected[1]})")
            stat=ImageStat.Stat(im.resize((128,228)))
            if sum(stat.stddev)/3 < 5: issues.append("ภาพเกือบเป็นสีเดียว/อาจว่างเปล่า")
            w,h=im.size; px=im.resize((64,114))
            # Flag strong white/cream frame edges; soft watercolor paper is not automatically rejected.
            pix=px.load(); edge=[]
            for x in range(64): edge.extend([pix[x,0],pix[x,113]])
            for y in range(1,113): edge.extend([pix[0,y],pix[63,y]])
            bright=sum(1 for r,g,b in edge if min(r,g,b)>238 and max(r,g,b)-min(r,g,b)<12)/len(edge)
            if bright>0.95: issues.append("ขอบภาพสว่างขาว/ครีมต่อเนื่อง อาจมีกรอบหรือขอบว่าง")
    except Exception as e:
        issues.append(f"เปิด/ถอดรหัสภาพไม่ได้: {type(e).__name__}: {e}")
    return issues
