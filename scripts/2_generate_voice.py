"""ขั้น 2: สร้างเสียงพากย์ทีละฉาก + วัดความยาวจริง -> output/audio/*.mp3 และอัปเดต script.json

ลำดับการทำงานตามสเปกข้อ 6.2:
1. พยายามสร้างทั้งคลิปด้วย Gemini TTS ก่อน (เสียงหลักเริ่มต้น: Orus)
   - เว้นระยะระหว่างฉาก >= 31 วินาที เพื่อไม่ชนโควตาฟรี (~2 RPM)
   - แปลงเสียงจาก response (รองรับทั้ง PCM ดิบ 24kHz 16-bit mono และ audio container) เป็น MP3
2. หากฉากใดฉากหนึ่งล้มเหลวครบโควตา retry -> ล้างไฟล์เสียงเดิม แล้วสร้างใหม่ทั้งคลิปด้วย edge-tts
   เพื่อป้องกันเสียงคนละคนปนกันในคลิปเดียว

ตัวแปร env ที่ปรับได้:
  - GEMINI_TTS_MODEL (ค่าเริ่มต้น: gemini-3.8-flash-tts รองรับภาษาไทย)
  - GEMINI_TTS_FALLBACK_MODELS (ค่าเริ่มต้น: ว่าง) ใช้เมื่อรุ่นหลักใช้ไม่ได้/โควตาเต็มตั้งแต่ฉากแรก
    (เลือกรุ่นที่ใช้ได้จากฉากแรก แล้วใช้รุ่นเดียวกันทั้งคลิปเพื่อให้เสียงเหมือนกันตลอด)
    หมายเหตุ: gemini-3.8-flash-lite-tts ไม่รองรับภาษาไทย จึงไม่ใส่เป็นรุ่นสำรอง ถ้า 3.8 ใช้ไม่ได้ระบบจะสลับไป edge-tts
    รุ่นเก่า gemini-3.1-flash-tts-preview และ gemini-2.5-flash-preview-tts ปิดแล้ว 17 พ.ย. 2026 (โค้ดไม่รองรับรูปแบบของรุ่น preview อีกต่อไป)
  - GEMINI_VOICE     (ค่าเริ่มต้น: Orus; ตัวเลือกอื่น: Charon, Algenib, Schedar, Fenrir, Puck)
  - GEMINI_TTS_DELAY (ค่าเริ่มต้น: 31 วินาที)
  - EDGE_VOICE       (ค่าเริ่มต้น: th-TH-NiwatNeural)
  - VOICE_RATE       (ค่าเริ่มต้น: -8%)
  - VOICE_PITCH      (ค่าเริ่มต้น: -2Hz)
  - AUDIO_TAIL_PAD   (ค่าเริ่มต้น: 0.4 วินาที เว้นความเงียบท้ายแต่ละฉาก)
  - voice_direction ในแต่ละ scene: curious / informative / excited / mysterious / emphatic / warm
    (ถ้า script.json รุ่นเก่าไม่มีฟิลด์นี้ จะใช้ informative)
"""
import asyncio
import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import edge_tts
import requests

OUT = pathlib.Path("output")
AUD = OUT / "audio"
AUD.mkdir(parents=True, exist_ok=True)

GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
GEMINI_TTS_FALLBACKS = [
    m.strip()
    for m in os.getenv("GEMINI_TTS_FALLBACK_MODELS", "").split(",")
    if m.strip()
]
GEMINI_TTS_MODELS = [GEMINI_TTS_MODEL] + [m for m in GEMINI_TTS_FALLBACKS if m != GEMINI_TTS_MODEL]
USED_TTS_MODEL = None
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Orus")
GEMINI_TTS_DELAY = float(os.getenv("GEMINI_TTS_DELAY", "31"))

EDGE_VOICE = os.getenv("EDGE_VOICE", os.getenv("VOICE", "th-TH-NiwatNeural"))
RATE = os.getenv("VOICE_RATE", "-8%")
PITCH = os.getenv("VOICE_PITCH", "-2Hz")

TAIL_PAD = float(os.getenv("AUDIO_TAIL_PAD", "0.4"))  # วินาที: เว้นความเงียบท้ายเสียงแต่ละฉาก ให้จังหวะไม่รีบ

MIN_TOTAL_WARN, MAX_TOTAL_WARN = 35.0, 95.0
MIN_TOTAL_HARD, MAX_TOTAL_HARD = 15.0, 150.0


def probe_duration(path: pathlib.Path) -> float:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"ffprobe อ่านความยาวไม่ได้: {path.name} ({r.stderr.strip()})")
    return float(r.stdout.strip())


def pad_tail(path: pathlib.Path, seconds: float = None):
    """เติมความเงียบท้ายไฟล์เสียง (ทำก่อนวัดความยาว จึงรวมอยู่ใน duration ที่ใช้เรนเดอร์)"""
    seconds = TAIL_PAD if seconds is None else seconds
    if seconds <= 0:
        return
    tmp = path.with_suffix(".pad.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-af", f"apad=pad_dur={seconds}",
         "-ar", "44100", "-ac", "1", "-b:a", "128k", str(tmp)],
        check=True,
    )
    tmp.replace(path)


def clear_audio_dir():
    for f in AUD.glob("*"):
        if f.is_file():
            f.unlink()


def parse_sample_rate(mime_type: str) -> int:
    m = re.search(r"rate=(\d+)", mime_type or "")
    return int(m.group(1)) if m else 24000


def convert_gemini_audio_to_mp3(raw_bytes: bytes, mime_type: str, out_mp3: pathlib.Path):
    """แปลง audio bytes จาก Gemini inlineData เป็น MP3 มาตรฐาน 44.1kHz mono"""
    mime = (mime_type or "").lower()
    tmp_in = out_mp3.with_suffix(".raw_in")
    tmp_in.write_bytes(raw_bytes)
    try:
        if "pcm" in mime or "l16" in mime or mime == "":
            rate = parse_sample_rate(mime)
            cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "s16le",
                "-ar",
                str(rate),
                "-ac",
                "1",
                "-i",
                str(tmp_in),
                "-ar",
                "44100",
                "-ac",
                "1",
                "-b:a",
                "128k",
                str(out_mp3),
            ]
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(tmp_in),
                "-ar",
                "44100",
                "-ac",
                "1",
                "-b:a",
                "128k",
                str(out_mp3),
            ]
        subprocess.run(cmd, check=True)
    finally:
        if tmp_in.exists():
            tmp_in.unlink()


class ModelUnavailable(Exception):
    """รุ่นนี้ใช้ไม่ได้ (ไม่มีสิทธิ์/ไม่พบรุ่น) ลองซ้ำไม่ช่วย"""


TTS_BASE_STYLE_EN = (
    "A friendly, warm and credible male narrator for short-form factual documentaries. "
    "Use natural, conversational Thai with clear articulation and expressive but balanced delivery. "
    "Speak at a moderately brisk pace, aiming roughly 8-10 percent faster than an unhurried documentary read, "
    "while keeping every word clear and preserving natural pauses. "
    "Sound engaging and human, never robotic, flat, rushed, theatrical or exaggerated."
)

VOICE_DIRECTION_STYLES = {
    "curious": "Scene emotion: curious and inviting. Add a light sense of wonder and anticipation, as if revealing an intriguing fact.",
    "informative": "Scene emotion: clear and informative. Prioritize calm confidence, precise explanation and easy comprehension.",
    "excited": "Scene emotion: pleasantly excited. Add lively energy and brighter emphasis, but do not shout or overact.",
    "mysterious": "Scene emotion: subtly mysterious. Use restrained suspense and intrigue without becoming dark or frightening.",
    "emphatic": "Scene emotion: emphatic. Give the key idea deliberate stress and a confident finish without sounding aggressive.",
    "warm": "Scene emotion: warm and reassuring. Use gentle friendliness and a human, inviting tone."
}


def build_tts_style(voice_direction: str = "informative") -> str:
    """รวมบุคลิกเสียงหลักกับอารมณ์เฉพาะฉาก; รองรับ script.json รุ่นเก่าที่ไม่มี voice_direction"""
    direction = str(voice_direction or "informative").strip().lower()
    if direction not in VOICE_DIRECTION_STYLES:
        direction = "informative"
    return f"{TTS_BASE_STYLE_EN} {VOICE_DIRECTION_STYLES[direction]}"


def build_tts_payload(model: str, narration: str, voice_direction: str = "informative") -> dict:
    """รุ่น 3.8 ขึ้นไป: text = บทพากย์เป๊ะๆ (โมเดลอ่านทุกคำ) ส่วนน้ำเสียงใส่ใน speech_metadata.style
    หาก script.json เก่าไม่มี voice_direction จะใช้ informative โดยอัตโนมัติ"""
    text = narration.strip()
    style = build_tts_style(voice_direction)
    return {
        "contents": [
            {"role": "user", "parts": [{"text": text, "speech_metadata": {"style": style}}]}
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"voice": GEMINI_VOICE}},
        },
    }


def call_gemini_tts_scene(narration: str, out_mp3: pathlib.Path, model: str, voice_direction: str = "informative"):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ไม่มี GEMINI_API_KEY")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = build_tts_payload(model, narration, voice_direction)

    for attempt in range(1, 4):
        try:
            r = requests.post(
                url,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=payload,
                timeout=120,
            )
            print(f"  [gemini-tts:{model}:{GEMINI_VOICE}] รอบ {attempt} -> HTTP {r.status_code}")
            if r.status_code >= 400 and r.status_code != 429:
                print(f"  เนื้อหาตอบกลับ: {r.text[:300]}")
            if r.status_code in (400, 403, 404):
                raise ModelUnavailable(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code == 429:
                wait_s = 35 * attempt
                print(f"  เจอ 429 หน่วงรอ {wait_s} วินาที...")
                time.sleep(wait_s)
                continue
            r.raise_for_status()
            body = r.json()
            parts = body["candidates"][0]["content"]["parts"]
            inline = next((p["inlineData"] for p in parts if "inlineData" in p), None)
            if not inline or not inline.get("data"):
                raise ValueError(f"ไม่พบ inlineData ใน response: {str(body)[:250]}")
            mime_type = inline.get("mimeType", "audio/pcm;rate=24000")
            if attempt == 1:
                print(f"  รูปแบบเสียงจาก API: {mime_type}")
            audio_bytes = base64.b64decode(inline["data"])
            convert_gemini_audio_to_mp3(audio_bytes, mime_type, out_mp3)
            if out_mp3.exists() and out_mp3.stat().st_size > 1000:
                return
            raise ValueError("ไฟล์ MP3 ที่แปลงได้เล็กผิดปกติ (<= 1 KB)")
        except ModelUnavailable:
            raise
        except Exception as e:
            print(f"  [gemini-tts] รอบ {attempt} ล้มเหลว: {type(e).__name__}: {e}")
            if attempt < 3:
                time.sleep(8 * attempt)

    raise RuntimeError(f"Gemini TTS ({model}) ล้มเหลวครบ 3 รอบสำหรับ {out_mp3.name}")


def generate_all_gemini(scenes: list[dict]) -> list[tuple[pathlib.Path, float]]:
    global USED_TTS_MODEL
    clear_audio_dir()
    results = []
    active_model = None  # รุ่นที่ล็อกแล้วหลังฉากแรกสำเร็จ
    for idx, s in enumerate(scenes):
        p = AUD / f"scene_{s['id']:02d}.mp3"
        direction = str(s.get("voice_direction", "informative")).strip().lower() or "informative"
        if direction not in VOICE_DIRECTION_STYLES:
            print(f"  WARNING: voice_direction '{direction}' ไม่รู้จัก -> ใช้ informative")
            direction = "informative"
        print(f"[Gemini TTS] ฉาก {s['id']}/{len(scenes)} | emotion={direction}...")
        candidates = [active_model] if active_model else GEMINI_TTS_MODELS
        last_err = None
        for model in candidates:
            try:
                call_gemini_tts_scene(s["narration"], p, model, direction)
                active_model = model
                last_err = None
                break
            except Exception as e:
                last_err = e
                print(f"  รุ่น {model} ใช้ไม่ได้: {e}")
        if last_err is not None:
            raise RuntimeError(f"ทุกรุ่น Gemini TTS ล้มเหลวที่ฉาก {s['id']}: {last_err}")
        pad_tail(p)
        dur = round(probe_duration(p), 2)
        if dur <= 0.3:
            raise RuntimeError(f"ความยาวเสียงฉาก {s['id']} สั้นผิดปกติ ({dur} วิ)")
        print(f"  -> {dur} วิ ({p.stat().st_size} bytes)")
        results.append((p, dur))
        if idx < len(scenes) - 1 and GEMINI_TTS_DELAY > 0:
            print(f"  พัก {GEMINI_TTS_DELAY:.0f} วิ เพื่อรักษาระดับโควตาฟรี...")
            time.sleep(GEMINI_TTS_DELAY)
    USED_TTS_MODEL = active_model
    return results


async def edge_tts_scene(text: str, path: pathlib.Path):
    for attempt in range(1, 4):
        try:
            await edge_tts.Communicate(text, EDGE_VOICE, rate=RATE, pitch=PITCH).save(str(path))
            if path.exists() and path.stat().st_size > 1000:
                return
            print(f"  [edge-tts] รอบ {attempt}: ไฟล์เสียงว่าง/เล็กผิดปกติ")
        except Exception as e:
            print(f"  [edge-tts] รอบ {attempt}: {type(e).__name__}: {e}")
        await asyncio.sleep(3 * attempt)
    raise RuntimeError(f"edge-tts ล้มเหลว: {path.name}")


async def generate_all_edge(scenes: list[dict]) -> list[tuple[pathlib.Path, float]]:
    clear_audio_dir()
    results = []
    for s in scenes:
        p = AUD / f"scene_{s['id']:02d}.mp3"
        print(f"[edge-tts:{EDGE_VOICE}] ฉาก {s['id']}/{len(scenes)}...")
        await edge_tts_scene(s["narration"], p)
        pad_tail(p)
        dur = round(probe_duration(p), 2)
        if dur <= 0.3:
            raise RuntimeError(f"ความยาวเสียงฉาก {s['id']} สั้นผิดปกติ ({dur} วิ)")
        print(f"  -> {dur} วิ ({p.stat().st_size} bytes)")
        results.append((p, dur))
    return results


def main():
    script_path = OUT / "script.json"
    if not script_path.exists():
        sys.exit("ไม่พบ output/script.json (ต้องรันขั้น 1 ก่อน)")

    data = json.loads(script_path.read_text(encoding="utf-8"))
    scenes = data["scenes"]

    provider_used = "gemini"
    try:
        results = generate_all_gemini(scenes)
    except Exception as e:
        print(f"WARNING: Gemini TTS ไม่สำเร็จ ({e}) -> สลับไปสร้างใหม่ทั้งคลิปด้วย edge-tts")
        provider_used = "edge"
        try:
            results = asyncio.run(generate_all_edge(scenes))
        except Exception as e2:
            sys.exit(f"สร้างเสียงล้มเหลวทั้ง Gemini TTS และ edge-tts: {e2}")

    total = 0.0
    for s, (p, dur) in zip(scenes, results):
        s["audio"] = str(p)
        s["duration"] = dur
        total += dur

    total = round(total, 2)
    data["total_duration"] = total
    data["voice_provider"] = provider_used
    data["voice_model"] = USED_TTS_MODEL if provider_used == "gemini" else EDGE_VOICE
    script_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"เสร็จขั้น 2 ({provider_used}) | ความยาวรวม {total:.2f} วินาที")

    if not (MIN_TOTAL_HARD <= total <= MAX_TOTAL_HARD):
        sys.exit(f"ความยาวเสียงรวม {total} วิ ออกนอกขอบเขตปลอดภัย ({MIN_TOTAL_HARD}-{MAX_TOTAL_HARD} วิ)")
    if not (MIN_TOTAL_WARN <= total <= MAX_TOTAL_WARN):
        print(f"WARNING: ความยาวรวม {total} วิ นอกช่วงเป้าหมาย {MIN_TOTAL_WARN}-{MAX_TOTAL_WARN} วิ")


if __name__ == "__main__":
    main()
