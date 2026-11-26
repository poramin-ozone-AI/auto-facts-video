"""ขั้น 3: สร้างภาพทีละฉาก -> output/images/*.png (1280x720)

ลำดับผู้ให้บริการ (สลับอัตโนมัติเมื่อตัวก่อนหน้าโควตาเต็ม/ล่ม):
  1) Cloudflare Workers AI  FLUX.2 klein 4B  (หลัก, 1280x720 ตรงๆ + ภาพอ้างอิงตัวละคร/สไตล์)
  2) Cloudflare Workers AI  รุ่นสำรอง         (CF_IMAGE_FALLBACK_MODELS = FLUX.1 schnell)
  3) Pollinations (ไม่ต้องใช้คีย์, จำกัด ~1 คำขอ/15 วินาที, อาจมีลายน้ำ)  -> ปิดได้ด้วย ENABLE_POLLINATIONS=0
ตัวที่ล้มเหลวด้วย 429/401/403/404 จะถูกข้ามไปตลอดการรันที่เหลือ

หมายเหตุ: ถ้าบางฉากต้องใช้ตัวสำรอง สไตล์ภาพอาจต่างจากฉากอื่นเล็กน้อย (ดู log ฟิลด์ image_provider ใน script.json)

โหมดทดสอบ: python scripts/3_generate_images.py --test   (สร้างแค่ 1 ฉาก stickman + 1 ฉาก object โดยไม่ทับ script.json)
Secrets: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID (ถ้าไม่มีจะข้าม Cloudflare ไปใช้ตัวสำรองเลย)
ตัวแปร env ที่ปรับได้:
  - CF_IMAGE_MODEL            (ค่าเริ่มต้น: @cf/black-forest-labs/flux-1-schnell)
  - CF_IMAGE_FALLBACK_MODELS  (ค่าเริ่มต้น: @cf/bytedance/stable-diffusion-xl-lightning)
  - CF_IMAGE_STEPS            (ค่าเริ่มต้น: 6; สูงสุด 8 ใช้กับ FLUX)
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
POLLINATIONS_GAP = 16.0  # วินาที (ผู้ใช้ไม่ล็อกอินจำกัด ~1 คำขอ/15 วินาที)

_last_pollinations = 0.0
REFS: dict = {}


class ProviderDown(Exception):
    """ตัวนี้ใช้ไม่ได้ต่อไปในการรันนี้ (โควตาเต็ม/ไม่มีสิทธิ์/ไม่พบรุ่น)"""


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


def no_ref_text(prompt: str) -> str:
    """ตัดประโยคที่อ้างถึง 'image 1/2' ออก สำหรับโมเดลที่ไม่รับภาพอ้างอิง"""
    return " ".join(x for x in prompt.split(". ") if "image 1" not in x and "image 2" not in x)


def gen_cloudflare(model: str, prompt: str) -> bytes:
    prompt = no_ref_text(prompt)
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
        raise ProviderDown("โควตาเต็มหรือเซิร์ฟเวอร์เต็ม (429)")
    r.raise_for_status()
    return image_bytes_from_response(r)


def prepare_refs() -> dict:
    """ตัดท่ายืนตัวแรกจากชีตตัวละคร และย่อภาพสไตล์ให้เล็กกว่า 512x512 (ข้อกำหนดของ FLUX.2 klein)"""
    refs = {}
    d = OUT / "refs"
    d.mkdir(parents=True, exist_ok=True)
    jobs = {
        "stickman": ("assets/stickman_ref.png", "crop=240:450:10:15"),
        "style": ("assets/style_bg_ref.png", "scale=480:-2"),
    }
    for key, (src, vf) in jobs.items():
        if not pathlib.Path(src).exists():
            print(f"WARNING: ไม่พบ {src} -> ข้ามภาพอ้างอิง {key}")
            continue
        dst = d / f"{key}.png"
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vf", vf, str(dst)],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and dst.exists():
            w, h = probe_size(dst)
            if w < 512 and h < 512:
                refs[key] = dst
        else:
            print(f"WARNING: เตรียมภาพอ้างอิง {key} ไม่สำเร็จ: {r.stderr.strip()[:200]}")
    return refs


def gen_cloudflare_klein(model: str, prompt: str, scene_type: str) -> bytes:
    """FLUX.2 klein: รับ width/height ตรงๆ (ได้ 16:9 ไม่ต้องครอป) และรับภาพอ้างอิงผ่าน multipart"""
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    fields = {"prompt": (None, prompt), "width": (None, "1280"), "height": (None, "720")}
    opened = []
    try:
        idx = 0
        order = ["stickman", "style"] if scene_type == "stickman" else ["style"]
        for key in order:
            if key in REFS:
                f = open(REFS[key], "rb")
                opened.append(f)
                fields[f"input_image_{idx}"] = (REFS[key].name, f, "image/png")
                idx += 1
        r = requests.post(url, headers=headers, files=fields, timeout=180)
    finally:
        for f in opened:
            f.close()
    print(f"  [cloudflare:{model}] HTTP {r.status_code}")
    if r.status_code in (401, 403, 404):
        raise ProviderDown(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code == 429:
        raise ProviderDown("โควตาเต็มหรือเซิร์ฟเวอร์เต็ม (429)")
    r.raise_for_status()
    return image_bytes_from_response(r)


def gen_pollinations(prompt: str) -> bytes:
    prompt = no_ref_text(prompt)
    global _last_pollinations
    wait = POLLINATIONS_GAP - (time.time() - _last_pollinations)
    if wait > 0:
        time.sleep(wait)
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500])
    params = {"width": 1344, "height": 768, "model": "flux", "nologo": "true"}
    r = requests.get(url, params=params, timeout=180)
    _last_pollinations = time.time()
    print(f"  [pollinations] HTTP {r.status_code}")
    if r.status_code in (401, 403, 404):
        raise ProviderDown(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code == 429:
        raise ProviderDown("ถูกจำกัดอัตรา (429)")
    r.raise_for_status()
    return image_bytes_from_response(r)


def build_providers() -> list[tuple[str, callable]]:
    providers = []
    if ACCOUNT_ID and API_TOKEN:
        for m in [CF_MODEL] + [x for x in CF_FALLBACKS if x != CF_MODEL]:
            if "flux-2" in m:
                providers.append((f"cloudflare:{m}", lambda p, t, m=m: gen_cloudflare_klein(m, p, t)))
            else:
                providers.append((f"cloudflare:{m}", lambda p, t, m=m: gen_cloudflare(m, p)))
    else:
        print("WARNING: ไม่มี CLOUDFLARE_* ใน Secrets -> ข้าม Cloudflare")
    if ENABLE_POLLINATIONS:
        providers.append(("pollinations", lambda p, t: gen_pollinations(p)))
    if not providers:
        sys.exit("ไม่มีผู้ให้บริการสร้างภาพที่ใช้งานได้ (ตรวจ Secrets CLOUDFLARE_* หรือเปิด ENABLE_POLLINATIONS)")
    return providers


def generate(prompt: str, scene_type: str, raw_path: pathlib.Path, providers, dead: set) -> str:
    """ลองตามลำดับผู้ให้บริการ คืนชื่อผู้ให้บริการที่สำเร็จ"""
    for name, fn in providers:
        if name in dead:
            continue
        for attempt in range(1, 4):
            try:
                data = fn(prompt, scene_type)
                raw_path.write_bytes(data)
                if raw_path.stat().st_size > 5000:
                    return name
                print(f"  [{name}] รอบ {attempt}: ไฟล์ภาพเล็กผิดปกติ ({raw_path.stat().st_size} bytes)")
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


def to_16x9(raw: pathlib.Path, final: pathlib.Path):
    """ปรับเป็น 1280x720 โดย 'ไม่ตัดภาพ': ถ้าต้นฉบับไม่ใช่ 16:9 จะย่อให้พอดีความสูงแล้วเติมขอบข้างด้วยภาพเดียวกันที่เบลอ"""
    w, h = probe_size(raw)
    print(f"  ขนาดที่ได้จากโมเดล: {w}x{h}")
    if abs(w / h - 16 / 9) < 0.02:
        vf = "scale=1280:720:flags=lanczos"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vf", vf, str(final)]
    else:
        fc = (
            "[0:v]split[a][b];"
            "[a]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,boxblur=30:5[bg];"
            "[b]scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-filter_complex", fc, str(final)]
    subprocess.run(cmd, check=True)
    if not final.exists() or final.stat().st_size <= 5000:
        sys.exit(f"ไฟล์ภาพสุดท้ายเล็กผิดปกติ: {final}")
    if probe_size(final) != (1280, 720):
        sys.exit(f"ขนาดภาพสุดท้ายผิด: {final}")


def main():
    script_path = OUT / "script.json"
    if not script_path.exists():
        sys.exit("ไม่พบ output/script.json (ต้องรันขั้น 1 ก่อน)")

    test = "--test" in sys.argv
    data = json.loads(script_path.read_text(encoding="utf-8"))
    scenes = data["scenes"]
    if test:
        pick, seen = [], set()
        for s in scenes:
            if s["type"] not in seen:
                pick.append(s)
                seen.add(s["type"])
        scenes = pick

    REFS.update(prepare_refs())
    print("ภาพอ้างอิงที่ใช้ได้:", sorted(REFS))
    providers = build_providers()
    dead: set = set()
    used = []

    for s in scenes:
        print(f"ฉาก {s['id']} ({s['type']})")
        raw = IMG / f"raw_{s['id']:02d}.png"
        final = IMG / f"scene_{s['id']:02d}.png"
        name = generate(build_prompt(s), s["type"], raw, providers, dead)
        to_16x9(raw, final)
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
