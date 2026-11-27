"""ขั้น 3: สร้างภาพทีละฉาก -> output/images/*.png (720x1280 แนวตั้ง 9:16)

ลำดับผู้ให้บริการ (สลับอัตโนมัติเมื่อตัวก่อนหน้าโควตาเต็ม/ล่ม):
  1) Cloudflare Workers AI  FLUX.2 klein 4B  (หลัก, สั่ง 720x1280 ตรงๆ, ใช้ข้อความล้วนไม่ส่งภาพอ้างอิง)
  2) Cloudflare Workers AI  รุ่นสำรอง         (CF_IMAGE_FALLBACK_MODELS = FLUX.1 schnell)
  3) Pollinations (ไม่ต้องใช้คีย์, จำกัด ~1 คำขอ/15 วินาที, อาจมีลายน้ำ)  -> ปิดได้ด้วย ENABLE_POLLINATIONS=0
ตัวที่ล้มเหลวด้วย 401/403/404 จะถูกข้ามไปตลอดการรันที่เหลือ ส่วน 429 จะรอแล้วลองซ้ำ 1 ครั้งก่อน ถ้ายัง 429 ค่อยข้าม

หมายเหตุ: ถ้าบางฉากต้องใช้ตัวสำรอง สไตล์ภาพอาจต่างจากฉากอื่นเล็กน้อย (ดู log ฟิลด์ image_provider ใน script.json)

โหมดทดสอบ: python scripts/3_generate_images.py --test   (สร้างแค่ 2 ฉาก คือฉากแรกกับฉากกลาง โดยไม่ทับ script.json)
Secrets: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID (ถ้าไม่มีจะข้าม Cloudflare ไปใช้ตัวสำรองเลย)
ตัวแปร env ที่ปรับได้:
  - CF_IMAGE_MODEL            (ค่าเริ่มต้น: @cf/black-forest-labs/flux-2-klein-4b)
  - CF_IMAGE_FALLBACK_MODELS  (ค่าเริ่มต้น: @cf/black-forest-labs/flux-1-schnell)
  - CF_IMAGE_STEPS            (ค่าเริ่มต้น: 6; สูงสุด 8 ใช้กับ FLUX.1 schnell เท่านั้น klein ไม่ใช้)
  - ENABLE_POLLINATIONS       (ค่าเริ่มต้น: 1)
"""
import base64
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.parse
import requests
from style import build_prompt
from image_quality import inspect_image

OUT = pathlib.Path("output")
IMG = OUT / "images"
IMG.mkdir(parents=True, exist_ok=True)

CF_MODEL = os.getenv("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-2-klein-4b")
CF_FALLBACKS = [
    m.strip()
    for m in os.getenv("CF_IMAGE_FALLBACK_MODELS", "@cf/black-forest-labs/flux-1-schnell").split(",")
    if m.strip()
]
STEPS = min(8, max(1, int(os.getenv("CF_IMAGE_STEPS", "6"))))
ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
ENABLE_POLLINATIONS = os.getenv("ENABLE_POLLINATIONS", "1") != "0"
W, H = 720, 1280  # คลิปแนวตั้ง 9:16
POLLINATIONS_GAP = 16.0  # วินาที (ผู้ใช้ไม่ล็อกอินจำกัด ~1 คำขอ/15 วินาที)

_last_pollinations = 0.0


class ProviderDown(Exception):
    """ตัวนี้ใช้ไม่ได้ต่อไปในการรันนี้ (ไม่มีสิทธิ์/ไม่พบรุ่น หรือ 429 ซ้ำหลังรอแล้ว)"""


class RateLimited(Exception):
    """ได้ 429: รอสักครู่แล้วลองซ้ำ 1 ครั้ง ถ้ายัง 429 ค่อยถือว่าตัวนี้ใช้ไม่ได้"""


def probe_size(path: pathlib.Path) -> tuple[int, int]:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or "," not in r.stdout:
        raise RuntimeError(f"ffprobe อ่านขนาดภาพไม่ได้: {path.name} ({r.stderr.strip()})")
    w, h = r.stdout.strip().split(",")[:2]
    return int(w), int(h)


def image_bytes_from_response(r: requests.Response) -> bytes:
    """รองรับทั้ง JSON {result:{image:base64}} (FLUX) และไฟล์ภาพดิบ (SDXL, Pollinations)"""
    ctype = r.headers.get("content-type", "").lower()
    if ctype.startswith("image/"):
        return r.content
    payload = r.json()
    res = payload.get("result", payload) if isinstance(payload, dict) else payload
    if isinstance(res, dict) and res.get("image"):
        return base64.b64decode(res["image"])
    raise ValueError(f"ไม่พบภาพใน response: {str(payload)[:250]}")


def gen_cloudflare(model: str, prompt: str) -> bytes:
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}
    body = {"prompt": prompt}
    if "flux-1" in model:
        body["steps"] = STEPS
    r = requests.post(url, headers=headers, json=body, timeout=120)
    print(f"  [cloudflare:{model}] HTTP {r.status_code}")
    if r.status_code in (401, 403, 404):
        raise ProviderDown(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code == 429:
        raise RateLimited("โควตาเต็มหรือเซิร์ฟเวอร์เต็ม (429)")
    r.raise_for_status()
    return image_bytes_from_response(r)


def gen_cloudflare_klein(model: str, prompt: str) -> bytes:
    """FLUX.2 klein: รับ width/height ตรงๆ (ได้ 720x1280 ไม่ต้องครอป) ต้องส่งแบบ multipart เสมอ (ไม่ส่งภาพอ้างอิง)"""
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    fields = {"prompt": (None, prompt), "width": (None, str(W)), "height": (None, str(H))}
    r = requests.post(url, headers=headers, files=fields, timeout=180)
    print(f"  [cloudflare:{model}] HTTP {r.status_code}")
    if r.status_code in (401, 403, 404):
        raise ProviderDown(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code == 429:
        raise RateLimited("โควตาเต็มหรือเซิร์ฟเวอร์เต็ม (429)")
    r.raise_for_status()
    return image_bytes_from_response(r)


def gen_pollinations(prompt: str) -> bytes:
    global _last_pollinations
    wait = POLLINATIONS_GAP - (time.time() - _last_pollinations)
    if wait > 0:
        time.sleep(wait)
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500])
    params = {"width": 768, "height": 1344, "model": "flux", "nologo": "true"}
    r = requests.get(url, params=params, timeout=180)
    _last_pollinations = time.time()
    print(f"  [pollinations] HTTP {r.status_code}")
    if r.status_code in (401, 403, 404):
        raise ProviderDown(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code == 429:
        raise RateLimited("ถูกจำกัดอัตรา (429)")
    r.raise_for_status()
    return image_bytes_from_response(r)


def build_providers() -> list[tuple[str, callable]]:
    providers = []
    if ACCOUNT_ID and API_TOKEN:
        for m in [CF_MODEL] + [x for x in CF_FALLBACKS if x != CF_MODEL]:
            if "flux-2" in m:
                providers.append((f"cloudflare:{m}", lambda p, m=m: gen_cloudflare_klein(m, p)))
            else:
                providers.append((f"cloudflare:{m}", lambda p, m=m: gen_cloudflare(m, p)))
    else:
        print("WARNING: ไม่มี CLOUDFLARE_* ใน Secrets -> ข้าม Cloudflare")
    if ENABLE_POLLINATIONS:
        providers.append(("pollinations", lambda p: gen_pollinations(p)))
    if not providers:
        sys.exit("ไม่มีผู้ให้บริการสร้างภาพที่ใช้งานได้ (ตรวจ Secrets CLOUDFLARE_* หรือเปิด ENABLE_POLLINATIONS)")
    return providers


RATE_LIMIT_WAIT = 30  # วินาที: รอก่อนลองซ้ำเมื่อเจอ 429


def generate(prompt: str, raw_path: pathlib.Path, providers, dead: set) -> str:
    """ลองตามลำดับผู้ให้บริการ คืนชื่อผู้ให้บริการที่สำเร็จ"""
    for name, fn in providers:
        if name in dead:
            continue
        rate_limited_once = False
        for attempt in range(1, 4):
            try:
                data = fn(prompt)
                raw_path.write_bytes(data)
                if raw_path.stat().st_size > 5000:
                    return name
                print(f"  [{name}] รอบ {attempt}: ไฟล์ภาพเล็กผิดปกติ ({raw_path.stat().st_size} bytes)")
            except RateLimited as e:
                if rate_limited_once:
                    print(f"  [{name}] 429 ซ้ำหลังรอแล้ว -> ข้ามตัวนี้ตลอดการรัน ({e})")
                    dead.add(name)
                    break
                rate_limited_once = True
                print(f"  [{name}] เจอ 429 -> รอ {RATE_LIMIT_WAIT} วินาทีแล้วลองซ้ำ 1 ครั้ง")
                time.sleep(RATE_LIMIT_WAIT)
                continue
            except ProviderDown as e:
                print(f"  [{name}] ใช้ไม่ได้ต่อไปในการรันนี้ -> {e}")
                dead.add(name)
                break
            except Exception as e:
                body = getattr(getattr(e, "response", None), "text", "") or ""
                print(f"  [{name}] รอบ {attempt}: {type(e).__name__}: {e} {body[:200]}")
            time.sleep(4)
        else:
            print(f"  [{name}] ล้มเหลวฉากนี้ -> ลองตัวถัดไป")
    sys.exit(f"สร้างภาพไม่สำเร็จทุกผู้ให้บริการ: {raw_path.name}")


def to_9x16(raw: pathlib.Path, final: pathlib.Path):
    """ปรับเป็น 720x1280 โดย 'ไม่ตัดภาพ': ถ้าต้นฉบับไม่ใช่ 9:16 จะย่อให้พอดีความกว้างแล้วเติมขอบบน/ล่างด้วยภาพเดียวกันที่เบลอ"""
    w, h = probe_size(raw)
    print(f"  ขนาดที่ได้จากโมเดล: {w}x{h}")
    if abs(w / h - W / H) < 0.02:
        vf = f"scale={W}:{H}:flags=lanczos"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vf", vf, str(final)]
    else:
        fc = (
            "[0:v]split[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:5[bg];"
            f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-filter_complex", fc, str(final)]
    subprocess.run(cmd, check=True)
    if not final.exists() or final.stat().st_size <= 5000:
        sys.exit(f"ไฟล์ภาพสุดท้ายเล็กผิดปกติ: {final}")
    if probe_size(final) != (W, H):
        sys.exit(f"ขนาดภาพสุดท้ายผิด: {final}")


def main():
    script_path = OUT / "script.json"
    if not script_path.exists():
        sys.exit("ไม่พบ output/script.json (ต้องรันขั้น 1 ก่อน)")

    test = "--test" in sys.argv
    data = json.loads(script_path.read_text(encoding="utf-8"))
    scenes = data["scenes"]
    if test:
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
        if chosen:
            scenes = chosen
        else:
            scenes = [scenes[0]] if len(scenes) < 2 else [scenes[0], scenes[len(scenes) // 2]]
        print(f"[โหมดทดสอบภาพ] ฉากที่ใช้: {[s['id'] for s in scenes]}")

    providers = build_providers()
    dead: set = set()
    used = []

    for s in scenes:
        print(f"ฉาก {s['id']}")
        raw = IMG / f"raw_{s['id']:02d}.png"
        final = IMG / f"scene_{s['id']:02d}.png"
        prompt = build_prompt(s)
        name = generate(prompt, raw, providers, dead)
        to_9x16(raw, final)
        qc_issues = inspect_image(final)
        if qc_issues:
            print(f"  Image QC ไม่ผ่านจาก {name}: {'; '.join(qc_issues)} -> ลองผู้ให้บริการสำรอง")
            dead.add(name)
            raw.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            name = generate(prompt, raw, providers, dead)
            to_9x16(raw, final)
            qc_issues = inspect_image(final)
            if qc_issues:
                sys.exit(f"Image QC ไม่ผ่านฉาก {s['id']} แม้ใช้ตัวสำรอง: {'; '.join(qc_issues)} | หยุดเพื่อไม่ใช้ภาพเสี่ยง")
        s["image"] = str(final)
        s["image_provider"] = name
        used.append(name)

    if len(set(used)) > 1:
        print(f"WARNING: คลิปนี้ใช้ภาพจากหลายผู้ให้บริการ: {sorted(set(used))} (สไตล์อาจไม่เท่ากันทุกฉาก)")
    if "pollinations" in used:
        print("WARNING: มีภาพจาก Pollinations ซึ่งอาจมีลายน้ำ ตรวจภาพก่อนโพสต์")

    if not test:
        script_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("เสร็จขั้น 3" + (" (โหมดทดสอบ)" if test else ""))


if __name__ == "__main__":
    main()
