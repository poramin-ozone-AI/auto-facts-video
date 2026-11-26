"""ขั้น 1: สร้างบทความรู้แปลกๆ + แบ่งฉาก -> output/script.json

ผู้ให้บริการ: Gemini (หลัก, ลองหลายรุ่นตามลำดับ) -> Groq (สำรอง) ทั้งคู่มี free tier
Secrets: GEMINI_API_KEY (จำเป็น), GROQ_API_KEY (แนะนำเป็นตัวสำรอง)
ตัวแปร env ที่ปรับได้:
  - GEMINI_MODEL            (ค่าเริ่มต้น: gemini-3.8-flash)
  - GEMINI_FALLBACK_MODELS  (ค่าเริ่มต้น: gemini-3.6-flash,gemini-3.5-flash-lite  คั่นด้วยจุลภาค)
  - GROQ_MODEL              (ค่าเริ่มต้น: openai/gpt-oss-120b)

หมายเหตุ: สคริปต์นี้ไม่บันทึกหัวข้อลง topics_history.txt อีกต่อไป
ระบบจะบันทึกหลังเรนเดอร์คลิปสำเร็จแล้วเท่านั้น (scripts/5_save_history.py)
"""
import datetime
import json
import os
import pathlib
import re
import sys
import time
import requests

OUT = pathlib.Path("output")
OUT.mkdir(exist_ok=True)
HISTORY = OUT / "topics_history.txt"

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACKS = [
    m.strip()
    for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.5-flash-lite").split(",")
    if m.strip()
]
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# เสียงไทยพูดประมาณ 13-16 ตัวอักษร/วินาที -> 40-90 วิ ~ 520-1350 ตัวอักษร (ค่าจริงวัดในขั้น 2)
MIN_CHARS, MAX_CHARS = 450, 1400
MIN_SCENES, MAX_SCENES = 6, 12

# หมวดหัวข้อประจำวัน (หมุนตามเลขวันของปี UTC) กันหัวข้อกลุ่มเดียวกันออกติดกันหลายวัน
CATEGORIES = [
    "ร่างกายมนุษย์และสุขภาพ",
    "อวกาศและดาราศาสตร์",
    "สัตว์",
    "ประวัติศาสตร์และอารยธรรม",
    "จิตวิทยาและสมอง",
    "ธรรมชาติ พืช และโลกของเรา",
    "ฟิสิกส์ เคมี และสิ่งประดิษฐ์",
    "ทะเลและมหาสมุทร",
]


def todays_category() -> str:
    day = datetime.datetime.now(datetime.timezone.utc).date().toordinal()
    return CATEGORIES[day % len(CATEGORIES)]


PROMPT = """คุณเป็นนักเขียนบทคลิปสั้น "ความรู้แปลกๆ ที่คนส่วนใหญ่ไม่รู้" ภาษาไทย
หัวข้อที่ใช้ไปแล้ว (ห้ามซ้ำหรือใกล้เคียง):
{history}

หมวดของวันนี้ (ให้เลือกหัวข้อใหม่จากหมวดนี้): {category}

เงื่อนไข:
- เลือกข้อเท็จจริงที่ตรวจสอบได้จริงทางวิทยาศาสตร์ ประวัติศาสตร์ ธรรมชาติ หรือจิตวิทยา ห้ามแต่งหรือเดา ถ้าไม่มั่นใจให้เลือกเรื่องอื่น
- เปิดด้วยประโยคดึงความสนใจใน 1-2 ประโยคแรก และปิดด้วยประโยคสรุปสั้นๆ ที่น่าจดจำ
- น้ำเสียงนุ่มนวล หนักแน่น น่าเชื่อถือ เหมาะกับการพากย์สารคดีสั้น
- บทพากย์รวมกัน {min_c}-{max_c} ตัวอักษร แบ่งเป็น {min_s}-{max_s} ฉาก
- แต่ละฉากมี image_prompt เป็นภาษาอังกฤษ บรรยายภาพเดียว ชัดเจน เป็นภาพแนวตั้ง (9:16) วางจุดเด่นไว้กลางภาพ
- แต่ละฉากต้องบรรยายให้ครบในตัวเอง ไม่อ้างถึงภาพก่อนหน้า ไม่ต้องคงตัวละครเดิมต่อเนื่อง จะเป็นสัตว์ สิ่งของ ธรรมชาติ หรือคนก็ได้ตามเนื้อหา (ภาพทั้งหมดจะถูกวาดเป็นการ์ตูนสีน้ำน่ารัก)
- image_prompt ของแต่ละฉากต้องวาดสิ่งที่ narration ของฉากนั้นพูดถึงโดยตรง ห้ามเป็นภาพบรรยากาศทั่วไปที่ไม่เกี่ยวกับประโยคนั้น
- ถ้าสิ่งที่พูดถึงมองไม่เห็นจากภายนอก (เช่น ใต้ดิน ภายในร่างกาย จุลชีพ ใต้ทะเลลึก ภายในอะตอม) ให้ image_prompt เป็นภาพตัดขวางหรือภาพขยายใกล้ที่เห็นสิ่งนั้นชัดเจน ขึ้นต้นด้วยคำว่า cross-section cutaway view หรือ close-up macro view เช่น cross-section cutaway view of soil showing tree roots connected by thin glowing fungal threads
- ห้ามมีตัวหนังสือ ตัวเลข เครื่องหมายคำพูด บอลลูนคำพูด หรือข้อความใดๆ ในภาพ

ตอบเป็น JSON อย่างเดียว ไม่มีข้อความอื่น ตามรูปแบบ:
{{"topic": "หัวข้อสั้นๆ", "title": "ชื่อคลิป",
  "scenes": [{{"id": 1, "narration": "ข้อความพากย์", "image_prompt": "..."}}]}}"""


class NonRetryable(Exception):
    """ข้อผิดพลาดที่ลองซ้ำกับโมเดลเดิมไม่ช่วย (429, 400, 403, 404) -> ข้ามไปตัวถัดไปทันที"""


def check_status(tag: str, r: requests.Response):
    print(f"[{tag}] HTTP {r.status_code}")
    if r.status_code in (400, 401, 403, 404, 429):
        raise NonRetryable(f"HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()


def call_gemini(prompt: str, model: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = requests.post(
        url,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        timeout=120,
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.9,
            },
        },
    )
    check_status(f"gemini:{model}", r)
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def call_groq(prompt: str, model: str) -> str:
    key = os.environ["GROQ_API_KEY"]
    body = {
        "model": model,
        "temperature": 0.9,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
        # โควตาฟรีของ Groq จำกัดโทเคน/นาทีต่ำ (~8K) จึงจำกัดการ "คิด" และความยาวคำตอบ
        "max_completion_tokens": 6000,
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=120,
        json=body,
    )
    check_status(f"groq:{model}", r)
    return r.json()["choices"][0]["message"]["content"]


def parse(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(cleaned)


def norm(t: str) -> str:
    return re.sub(r"\s+", "", str(t)).lower()


def validate(d: dict, used_topics: list[str]) -> list[str]:
    """คืนรายการข้อผิดพลาด (ว่าง = ผ่าน)"""
    errs = []
    if not isinstance(d, dict):
        return ["ผลลัพธ์ไม่ใช่ JSON object"]
    for k in ("topic", "title", "scenes"):
        if not d.get(k):
            errs.append(f"ขาดฟิลด์ {k}")
    if d.get("topic") and norm(d["topic"]) in {norm(t) for t in used_topics}:
        errs.append(f"หัวข้อ '{d['topic']}' ซ้ำกับที่เคยใช้แล้ว")
    scenes = d.get("scenes") or []
    if not isinstance(scenes, list) or not (MIN_SCENES <= len(scenes) <= MAX_SCENES):
        errs.append(f"จำนวนฉาก {len(scenes) if isinstance(scenes, list) else 0} ต้องอยู่ระหว่าง {MIN_SCENES}-{MAX_SCENES}")
        return errs
    for i, s in enumerate(scenes, 1):
        if not isinstance(s, dict):
            errs.append(f"ฉาก {i}: รูปแบบไม่ถูกต้อง")
            continue
        if not str(s.get("narration", "")).strip():
            errs.append(f"ฉาก {i}: narration ว่าง")
        if len(str(s.get("image_prompt", "")).strip()) < 15:
            errs.append(f"ฉาก {i}: image_prompt สั้นเกินไป")
        s["id"] = i
    total = sum(len(str(s.get("narration", "")).strip()) for s in scenes if isinstance(s, dict))
    if not (MIN_CHARS <= total <= MAX_CHARS):
        errs.append(f"ความยาวบทรวม {total} ตัวอักษร ต้องอยู่ระหว่าง {MIN_CHARS}-{MAX_CHARS}")
    return errs


def main():
    all_history = HISTORY.read_text(encoding="utf-8").strip().splitlines() if HISTORY.exists() else []
    history = all_history[-60:]
    prompt = PROMPT.format(
        history="\n".join(f"- {h}" for h in history) or "(ยังไม่มี)",
        min_c=MIN_CHARS,
        max_c=MAX_CHARS,
        min_s=MIN_SCENES,
        max_s=MAX_SCENES,
        category=todays_category(),
    )
    print(f"หมวดประจำวัน: {todays_category()}")

    # (ชื่อผู้ให้บริการ, โมเดล, ฟังก์ชัน)
    providers = []
    if os.getenv("GEMINI_API_KEY"):
        for m in [GEMINI_MODEL] + [x for x in GEMINI_FALLBACKS if x != GEMINI_MODEL]:
            providers.append(("gemini", m, call_gemini))
    if os.getenv("GROQ_API_KEY"):
        providers.append(("groq", GROQ_MODEL, call_groq))
    if not providers:
        sys.exit("ไม่พบ GEMINI_API_KEY หรือ GROQ_API_KEY ใน Secrets")

    for name, model, fn in providers:
        for attempt in range(1, 4):
            try:
                raw = fn(prompt, model)
                data = parse(raw)
                errs = validate(data, all_history)
                if not errs:
                    data["provider"] = name
                    data["model"] = model
                    (OUT / "script.json").write_text(
                        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    total = sum(len(s["narration"].strip()) for s in data["scenes"])
                    print(f"OK ({name}:{model}) หัวข้อ: {data['topic']} | {len(data['scenes'])} ฉาก | {total} ตัวอักษร")
                    return
                print(f"[{name}:{model}] รอบ {attempt}: บทไม่ผ่านการตรวจ -> {errs}")
            except NonRetryable as e:
                print(f"[{name}:{model}] ใช้ไม่ได้ ข้ามไปตัวถัดไป -> {e}")
                break
            except Exception as e:
                print(f"[{name}:{model}] รอบ {attempt}: {type(e).__name__}: {e}")
            time.sleep(5)
        print(f"[{name}:{model}] ล้มเหลว -> ลองตัวถัดไป")

    sys.exit("ล้มเหลวทุกผู้ให้บริการ ดู log ด้านบน")


if __name__ == "__main__":
    main()
