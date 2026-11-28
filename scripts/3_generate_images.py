"""ขั้น 3: สร้างภาพทีละฉาก -> output/images/*.png (720x1280 แนวตั้ง 9:16)

v4.4: ใช้โมเดลเดียวคือ Cloudflare Workers AI FLUX.2 klein 4B (สั่ง 720x1280 ตรงๆ ด้วย multipart, ข้อความล้วนไม่ส่งภาพอ้างอิง)
  - ไม่มีตัวสำรอง (ตัด FLUX.1 schnell และ Pollinations ออก) ภาพทุกฉากจึงมาจากโมเดลเดียวกัน สไตล์สอดคล้องกัน
  - ไม่มี Image QC เชิงภาพ ภาพที่ได้ถูกใช้เลย (ตรวจแค่ว่าไฟล์เปิดได้และขนาดถูกต้อง) -> ต้องดูคลิป/ภาพก่อนโพสต์เสมอ
  - ถ้า klein ล้มเหลวจริง (429 ซ้ำจนหมดรอบ, 401/403/404 หรือ error ซ้ำทุกรอบ) การรันจะล้มทันที ไม่มีคลิปของวันนั้น
    (หัวข้อจะไม่ถูกบันทึกเป็นใช้แล้ว) จึงให้ retry หลายรอบและรอ 429 นานขึ้นเพื่อให้ทนกว่าเดิม

v4.7: ตัวละครประจำคลิป (OZONE + ORBI) ส่งเป็นภาพอ้างอิง input_image_0..N (multipart) เฉพาะฉากที่ระบุ characters ใน script.json
  - เตรียมภาพอ้างอิงตอนรัน: ตัดขอบโปร่งใส -> แปะบนพื้น CHAR_REF_BG -> ย่อ/ขยายให้ด้านยาวสุด = CHAR_REF_MAX_SIDE (เอกสาร Cloudflare จำกัดภาพอ้างอิง < 512x512)
  - ถ้า Cloudflare ปฏิเสธเพราะภาพอ้างอิง (HTTP 400/422) หยุดการรันพร้อมข้อความชัดเจน ไม่ถอยไปวาดแบบไม่มีภาพอ้างอิงเงียบๆ
  - บันทึก prompt ที่ส่งจริงไว้ที่ output/images/prompt_NN.txt เพื่อตรวจย้อนหลัง
  - ตัวแปร env: CHARACTERS_ENABLED (1), CHAR_REF_MAX_SIDE (480), CHAR_REF_BG (white | cream | black)

โหมดทดสอบ: python scripts/3_generate_images.py --test   (สร้างแค่ 2 ฉาก คือฉากแรกกับฉากกลาง โดยไม่ทับ script.json)
Secrets: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID (จำเป็น ถ้าไม่มีจะหยุดทันที)
ตัวแปร env ที่ปรับได้:
  - CF_IMAGE_MODEL              (ค่าเริ่มต้น: @cf/black-forest-labs/flux-2-klein-4b)
  - IMAGE_MAX_ATTEMPTS          (ค่าเริ่มต้น: 5)  จำนวนรอบต่อฉากเมื่อเจอ error ทั่วไป (เครือข่าย 5xx ไฟล์ภาพเสีย/เล็กผิดปกติ)
  - IMAGE_RATE_LIMIT_RETRIES    (ค่าเริ่มต้น: 4)  จำนวนครั้งที่รอแล้วลองใหม่เมื่อเจอ 429 (ไม่นับรวมใน IMAGE_MAX_ATTEMPTS)
  - IMAGE_RATE_LIMIT_WAIT       (ค่าเริ่มต้น: 60) วินาทีที่รอเมื่อเจอ 429 ครั้งแรก ครั้งต่อไปรอเพิ่มเป็น 2x, 3x, ... (สูงสุด 300 วินาที/ครั้ง)
"""
import base64
import io
import json
import os
import pathlib
import subprocess
import sys
import time

import requests
from PIL import Image

from style import CHARACTERS, build_prompt, scene_characters

OUT = pathlib.Path("output")
IMG = OUT / "images"
IMG.mkdir(parents=True, exist_ok=True)

CF_MODEL = os.getenv("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-2-klein-4b").strip()
ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
W, H = 720, 1280  # คลิปแนวตั้ง 9:16
MIN_IMAGE_BYTES = 5000

MAX_ATTEMPTS = max(1, int(os.getenv("IMAGE_MAX_ATTEMPTS", "5")))
RATE_LIMIT_RETRIES = max(0, int(os.getenv("IMAGE_RATE_LIMIT_RETRIES", "4")))
RATE_LIMIT_WAIT = max(1, int(os.getenv("IMAGE_RATE_LIMIT_WAIT", "60")))
RATE_LIMIT_WAIT_CAP = 300
RETRY_BACKOFF = 4  # วินาที x เลขรอบ (สูงสุด 30)

# v4.7: ภาพอ้างอิงตัวละคร
CHAR_REF_MAX_SIDE = max(64, min(511, int(os.getenv("CHAR_REF_MAX_SIDE", "480"))))  # ต้องน้อยกว่า 512
CHAR_REF_BG = os.getenv("CHAR_REF_BG", "white").strip().lower()
_BG_COLORS = {"white": (255, 255, 255), "cream": (250, 244, 232), "black": (0, 0, 0)}
_REF_CACHE: dict[str, bytes] = {}
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


class FatalAPIError(Exception):
    """401/403/404: โทเคน/สิทธิ์/ชื่อรุ่นผิด ลองซ้ำไม่ช่วย -> หยุดการรัน"""


class RateLimited(Exception):
    """ได้ 429: รอแล้วลองใหม่ (ตามจำนวนครั้งที่กำหนด)"""


def image_bytes_from_response(r: requests.Response) -> bytes:
    """รองรับทั้ง JSON {result:{image:base64}} และไฟล์ภาพดิบ"""
    ctype = r.headers.get("content-type", "").lower()
    if ctype.startswith("image/"):
        return r.content
    payload = r.json()
    res = payload.get("result", payload) if isinstance(payload, dict) else payload
    if isinstance(res, dict) and res.get("image"):
        return base64.b64decode(res["image"])
    raise ValueError(f"ไม่พบภาพใน response: {str(payload)[:250]}")


def prepare_reference(char_id: str) -> bytes:
    """ภาพอ้างอิงตัวละคร -> PNG (RGB) ที่ตัดขอบโปร่งใสแล้วแปะบนพื้นเรียบ ด้านยาวสุด = CHAR_REF_MAX_SIDE (ไม่เกิน 511)"""
    if char_id in _REF_CACHE:
        return _REF_CACHE[char_id]
    path = pathlib.Path(CHARACTERS[char_id]["ref"])
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        sys.exit(f"ไม่พบภาพอ้างอิงตัวละคร '{char_id}': {path} (ต้อง commit ไฟล์ใน assets/characters/ ขึ้น repo)")
    with Image.open(path) as im:
        im = im.convert("RGBA")
    bbox = im.getchannel("A").point(lambda v: 255 if v > 10 else 0).getbbox()
    if bbox:
        pad = int(max(im.size) * 0.03)
        bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(im.width, bbox[2] + pad), min(im.height, bbox[3] + pad))
        im = im.crop(bbox)
    scale = CHAR_REF_MAX_SIDE / max(im.size)
    im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    bg = Image.new("RGBA", im.size, _BG_COLORS.get(CHAR_REF_BG, _BG_COLORS["white"]) + (255,))
    bg.alpha_composite(im)
    out = io.BytesIO()
    bg.convert("RGB").save(out, format="PNG")
    _REF_CACHE[char_id] = out.getvalue()
    return _REF_CACHE[char_id]


def gen_cloudflare_klein(model: str, prompt: str, refs: list[bytes] | None = None) -> bytes:
    """FLUX.2 klein: รับ width/height ตรงๆ (ได้ 720x1280 ไม่ต้องครอป) ต้องส่งแบบ multipart เสมอ
    v4.7: refs = ภาพอ้างอิง (PNG bytes) ส่งเป็น input_image_0..N ตามลำดับ (สูงสุด 4 ภาพ)"""
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    fields = {"prompt": (None, prompt), "width": (None, str(W)), "height": (None, str(H))}
    for i, data in enumerate((refs or [])[:4]):
        fields[f"input_image_{i}"] = (f"ref_{i}.png", data, "image/png")
    r = requests.post(url, headers=headers, files=fields, timeout=180)
    print(f"  [cloudflare:{model}] HTTP {r.status_code}" + (f" (ภาพอ้างอิง {len(refs)} ภาพ)" if refs else ""))
    if r.status_code in (401, 403, 404):
        raise FatalAPIError(f"HTTP {r.status_code}: {r.text[:200]}")
    if refs and r.status_code in (400, 422):
        raise FatalAPIError(
            f"HTTP {r.status_code} จากคำขอที่มีภาพอ้างอิง: {r.text[:300]} | ตรวจขนาดภาพอ้างอิง (CHAR_REF_MAX_SIDE ต้อง < 512) "
            "หรือสั่ง CHARACTERS_ENABLED=0 เพื่อปิดตัวละครชั่วคราว"
        )
    if r.status_code == 429:
        raise RateLimited("โควตาเต็มหรือเซิร์ฟเวอร์เต็ม (429)")
    r.raise_for_status()
    return image_bytes_from_response(r)


def check_image_file(path: pathlib.Path) -> tuple[int, int]:
    """ตรวจพื้นฐานเท่านั้น: ไฟล์ใหญ่พอ เปิดและถอดรหัสได้ -> คืน (กว้าง, สูง) ไม่ตรวจความสวย/เนื้อหา"""
    size = path.stat().st_size
    if size <= MIN_IMAGE_BYTES:
        raise ValueError(f"ไฟล์ภาพเล็กผิดปกติ ({size} bytes)")
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        im.load()
        return im.size


def generate_image(prompt: str, raw_path: pathlib.Path, fn, label: str = "ภาพ", sleep=None) -> None:
    """เรียกโมเดลจนได้ไฟล์ภาพที่เปิดได้ หรือหยุดการรัน (sys.exit) เมื่อล้มเหลวจริง

    - 429: รอ RATE_LIMIT_WAIT x n วินาทีแล้วลองใหม่ได้สูงสุด RATE_LIMIT_RETRIES ครั้ง
    - 401/403/404: หยุดทันที
    - error อื่น/ไฟล์เสีย: ลองใหม่ได้สูงสุด MAX_ATTEMPTS รอบ
    """
    pause = sleep or time.sleep
    attempts = 0
    rate_waits = 0
    last_error = ""
    while attempts < MAX_ATTEMPTS:
        try:
            raw_path.unlink(missing_ok=True)
            data = fn(prompt)
            raw_path.write_bytes(data)
            size = check_image_file(raw_path)
            print(f"  [{label}] สำเร็จ ขนาดจากโมเดล {size[0]}x{size[1]}")
            return
        except RateLimited as e:
            if rate_waits >= RATE_LIMIT_RETRIES:
                sys.exit(f"{label}: 429 ซ้ำหลังรอแล้ว {rate_waits} ครั้ง ({e}) -> หยุดการรัน (ไม่มีโมเดลสำรอง) รันใหม่ภายหลังเมื่อโควตารีเซ็ต")
            rate_waits += 1
            wait = min(RATE_LIMIT_WAIT_CAP, RATE_LIMIT_WAIT * rate_waits)
            print(f"  [{label}] เจอ 429 -> รอ {wait} วินาทีแล้วลองใหม่ ({rate_waits}/{RATE_LIMIT_RETRIES})")
            pause(wait)
            continue
        except FatalAPIError as e:
            sys.exit(f"{label}: Cloudflare ปฏิเสธคำขอ -> {e} | ตรวจ CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID / ชื่อรุ่น CF_IMAGE_MODEL")
        except Exception as e:
            attempts += 1
            body = getattr(getattr(e, "response", None), "text", "") or ""
            last_error = f"{type(e).__name__}: {e} {body[:200]}".strip()
            print(f"  [{label}] รอบ {attempts}/{MAX_ATTEMPTS} ล้มเหลว: {last_error}")
            if attempts < MAX_ATTEMPTS:
                pause(min(30, RETRY_BACKOFF * attempts))
    raw_path.unlink(missing_ok=True)
    sys.exit(f"{label}: สร้างภาพไม่สำเร็จหลังลอง {MAX_ATTEMPTS} รอบ ({last_error}) -> หยุดการรัน (ไม่มีโมเดลสำรอง)")


def finalize_image(raw: pathlib.Path, final: pathlib.Path) -> None:
    """ปรับเป็น 720x1280 (scale อย่างเดียว ไม่ครอป ไม่เติมขอบ) แล้วตรวจขนาดสุดท้าย"""
    w, h = check_image_file(raw)
    if abs(w / h - W / H) > 0.02:
        print(f"  WARNING: ภาพจากโมเดลไม่ใช่ 9:16 ({w}x{h}) จะถูกปรับเป็น {W}x{H} ตรงๆ อาจดูยืด/หด")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vf", f"scale={W}:{H}:flags=lanczos", str(final)],
        check=True,
    )
    if not final.exists() or final.stat().st_size <= MIN_IMAGE_BYTES:
        sys.exit(f"ไฟล์ภาพสุดท้ายเล็กผิดปกติ: {final}")
    if check_image_file(final) != (W, H):
        sys.exit(f"ขนาดภาพสุดท้ายผิด: {final}")


def select_scenes(data: dict, test: bool) -> list[dict]:
    scenes = data["scenes"]
    if not test:
        return scenes
    # v3.9: ใช้ฉากเดียวกับที่ขั้น 2 สร้างเสียงทดสอบไว้ (output/test_scenes.json) เพื่อให้ขั้น 4 เรนเดอร์ตัวอย่างได้
    # ถ้าไม่มีไฟล์นั้น ใช้ตรรกะเดิม (ฉากแรก + ฉากกลาง)
    chosen = []
    ts = OUT / "test_scenes.json"
    if ts.exists():
        try:
            ids = {int(x["id"]) for x in json.loads(ts.read_text(encoding="utf-8"))}
            chosen = [s for s in scenes if int(s["id"]) in ids]
        except Exception as e:
            print(f"WARNING: อ่าน test_scenes.json ไม่ได้ ({e}) -> ใช้ฉากแรก+ฉากกลาง")
    if not chosen:
        chosen = [scenes[0]] if len(scenes) < 2 else [scenes[0], scenes[len(scenes) // 2]]
    print(f"[โหมดทดสอบภาพ] ฉากที่ใช้: {[s['id'] for s in chosen]}")
    return chosen


def main():
    script_path = OUT / "script.json"
    if not script_path.exists():
        sys.exit("ไม่พบ output/script.json (ต้องรันขั้น 1 ก่อน)")
    if not (ACCOUNT_ID and API_TOKEN):
        sys.exit("ไม่พบ CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID ใน Secrets (v4.4 ใช้ Cloudflare FLUX.2 klein ตัวเดียว ไม่มีตัวสำรอง)")
    if "flux-2" not in CF_MODEL:
        print(f"WARNING: CF_IMAGE_MODEL '{CF_MODEL}' ไม่ใช่ FLUX.2 โค้ดนี้ส่งคำขอแบบ multipart ของ klein เท่านั้น")

    test = "--test" in sys.argv
    data = json.loads(script_path.read_text(encoding="utf-8"))
    scenes = select_scenes(data, test)
    provider = f"cloudflare:{CF_MODEL}"

    for s in scenes:
        print(f"ฉาก {s['id']}")
        raw = IMG / f"raw_{int(s['id']):02d}.png"
        final = IMG / f"scene_{int(s['id']):02d}.png"
        prompt = build_prompt(s)
        char_ids = scene_characters(s)
        refs = [prepare_reference(c) for c in char_ids]
        if char_ids:
            print(f"  ตัวละครในฉาก: {char_ids} (ส่งภาพอ้างอิง {len(refs)} ภาพ)")
        (IMG / f"prompt_{int(s['id']):02d}.txt").write_text(prompt, encoding="utf-8")
        generate_image(prompt, raw, lambda p, refs=refs: gen_cloudflare_klein(CF_MODEL, p, refs), label=f"ฉาก {s['id']}")
        finalize_image(raw, final)
        s["image"] = str(final)
        s["image_provider"] = provider

    if not test:
        script_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("เสร็จขั้น 3" + (" (โหมดทดสอบ)" if test else ""))


if __name__ == "__main__":
    main()
