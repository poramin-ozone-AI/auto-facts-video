"""ขั้น 1: สร้างบทความรู้แปลกๆ + แบ่งฉาก -> output/script.json

ผู้ให้บริการ: Gemini (หลัก, ลองหลายรุ่นตามลำดับ) -> Groq (สำรอง) ทั้งคู่มี free tier
Secrets: GEMINI_API_KEY (จำเป็น), GROQ_API_KEY (แนะนำเป็นตัวสำรอง)
ตัวแปร env ที่ปรับได้:
  - GEMINI_MODEL            (ค่าเริ่มต้น: gemini-3.8-flash)
  - GEMINI_FALLBACK_MODELS  (ค่าเริ่มต้น: gemini-3.6-flash,gemini-3.5-flash-lite  คั่นด้วยจุลภาค)
  - GROQ_MODEL              (ค่าเริ่มต้น: openai/gpt-oss-120b)
  - SCRIPT_MIN_CHARS / SCRIPT_MAX_CHARS  (ค่าเริ่มต้น: 520 / 1250 ตัวอักษรของบทพากย์รวม)
  - IMAGE_DETAIL_LEVEL      (ค่าเริ่มต้น: rich; ใช้ standard ถ้าภาพแน่นเกิน) กำหนดความละเอียดของ image_prompt และสไตล์ภาพ
  - SUBTITLES_ENABLED / SUBTITLE_KEYWORDS_ENABLED  (ค่าเริ่มต้น 1/1; ปิดอย่างใดอย่างหนึ่ง = ไม่ขอ keywords สำหรับซับสีเหลืองจาก AI)
  - GEMINI_MAX_OUTPUT_TOKENS / GROQ_MAX_TOKENS  (ค่าเริ่มต้น: 16384 / 6000) เพดานโทเคนคำตอบ กัน JSON ถูกตัด
  - VOICE_DIRECTIONS_ENABLED (ค่าเริ่มต้น: curious,informative,excited,mysterious,emphatic,warm
                              คั่นด้วยจุลภาค; ตัดบางอารมณ์ออกได้ informative จะอยู่เสมอ)

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

from style import IMAGE_DETAIL_LEVEL, extract_identities, strip_identity
from subtitles import KEYWORDS_ENABLED

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

# เสียงไทยพูดประมาณ 13-16 ตัวอักษร/วินาที -> 40-90 วิ ~ 520-1250 ตัวอักษร (ค่าจริงวัดในขั้น 2 แล้วค่อยปรับ)
# (v3.5 เป็น 450-1400 ซึ่งหลุดช่วง 40-90 วินาทีได้ทั้งสองด้าน)
MIN_CHARS = int(os.getenv("SCRIPT_MIN_CHARS", "520"))
MAX_CHARS = int(os.getenv("SCRIPT_MAX_CHARS", "1250"))
MIN_SCENES, MAX_SCENES = 6, 12
# เพดานโทเคนคำตอบ (v3.8: image_prompt ยาวขึ้น) Gemini นับโทเคนที่ "คิด" รวมด้วย จึงตั้งสูงไว้ก่อน
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "16384"))
# Groq ฟรีจำกัดโทเคน/นาทีต่ำ (~8K รวม prompt) จึงไม่ยกเพดานเกิน 6000 โดยอัตโนมัติ
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "6000"))

# ความยาว image_prompt (คำ ไม่นับบรรทัด IDENTITY LOCK): (ที่สั่งใน prompt, ขอบที่ validator ยอมรับ)
IMAGE_WORDS = {
    "rich": {"ask": (60, 120), "accept": (45, 160)},
    "standard": {"ask": (35, 70), "accept": (25, 110)},
}
IMG_ASK_MIN, IMG_ASK_MAX = IMAGE_WORDS[IMAGE_DETAIL_LEVEL]["ask"]
IMG_MIN_WORDS, IMG_MAX_WORDS = IMAGE_WORDS[IMAGE_DETAIL_LEVEL]["accept"]


KEYWORD_MAX_CHARS = 12
KEYWORD_STOPWORDS = {"และ", "แต่", "ที่", "ซึ่ง", "เพราะ", "หรือ", "ก็", "จึง", "เมื่อ", "ใน", "ของ", "คือ", "เป็น", "มี", "จะ", "ได้", "ไม่"}


def keyword_prompt_parts() -> tuple[str, str]:
    """คืน (บรรทัดกฎ keywords, ฟิลด์ใน JSON ตัวอย่าง) ว่างทั้งคู่ถ้าปิดซับสีเหลือง"""
    if not KEYWORDS_ENABLED:
        return "", ""
    rule = (
        f"- ทุกฉากใส่ keywords เป็นลิสต์ 1-2 คำที่เป็นคำสำคัญของฉากนั้น (ชื่อเฉพาะ ตัวเลข สิ่งที่น่าทึ่ง) เพื่อทำสีเน้นในซับ "
        f"ต้องคัดลอกจาก narration ของฉากนั้นตรงตัวทุกตัวอักษร ยาวไม่เกิน {KEYWORD_MAX_CHARS} ตัวอักษร "
        "ห้ามใช้คำทั่วไปอย่าง และ แต่ ที่ เป็น มี ได้\n"
    )
    return rule, ' "keywords": ["คำสำคัญ"],'


def image_rules() -> str:
    """กฎการเขียน image_prompt ตามระดับ IMAGE_DETAIL_LEVEL (ใส่ลงใน PROMPT)"""
    common_head = (
        f"- image_prompt เขียนเป็นภาษาอังกฤษ ความยาว {IMG_ASK_MIN}-{IMG_ASK_MAX} คำ (ไม่นับบรรทัด IDENTITY LOCK) "
        "เป็นประโยคบรรยายเชิงบวกว่า \"มีอะไรอยู่ในภาพ\" ห้ามใช้ negative prompt หรือคำปฏิเสธ เช่น no, without, not, avoid\n"
        "- ประโยคแรกของ image_prompt ต้องบอก \"ใคร/อะไร ทำอะไร ที่ไหน\" ให้ชัดก่อน (โมเดลภาพให้น้ำหนักช่วงต้นข้อความ) "
        "แล้วค่อยเพิ่มรายละเอียดตามลำดับ\n"
        "- ถ้า narration พูดถึงการกระทำของคนหรือสัตว์ ต้องเห็นตัวนั้นทำสิ่งนั้นจริงในภาพด้วยท่าทางที่ชัดเจน "
        "ห้ามวาดแค่ยานพาหนะ สิ่งของ หรือสถานที่เปล่าๆ (เช่น พูดถึงนักพายเรือ ต้องมีนักพายกำลังออกแรงดึงไม้พาย ไม่ใช่เรือเปล่า)\n"
    )
    if IMAGE_DETAIL_LEVEL == "rich":
        body = (
            "- แยกชั้นภาพให้ชัด: ฉากหน้า (foreground) ฉากกลาง (middle ground) และฉากหลัง (background)\n"
            "- ใส่ของประกอบ 2-3 อย่างที่เกี่ยวกับข้อเท็จจริงของฉากนั้น เช่น โล่ทรงกลม เชือก ธงใบเรือ\n"
            "- ระบุแสงและบรรยากาศ เช่น หมอกเทาเงินลอยเป็นชั้น แสงรำไรผ่านม่านหมอก\n"
            "- ใส่ไอเดียเชิงสัญลักษณ์หรือจินตนาการ 1 อย่างต่อฉาก ที่ช่วยสื่อข้อเท็จจริงนั้น เช่น ผลึก sunstone ชูส่องฟ้า นกกาที่ปล่อยบินนำทาง\n"
            "- แม้มีรายละเอียดมาก จุดโฟกัสหลักต้องยังชัดเจนเพียงจุดเดียว ไม่ให้ภาพรก\n"
            "- ถ้าข้อเท็จจริงมีหลายองค์ประกอบ ให้แตกเป็นหลายฉากแทนการยัดทุกอย่างไว้ในภาพเดียว แต่ห้ามเกิน "
            f"{MAX_SCENES} ฉาก\n"
            "- ตัวอย่างโครงของ image_prompt (ใช้เป็นแนวทางเท่านั้น ห้ามคัดลอกเนื้อหาหรือธีมไวกิ้ง): \"Bearded Viking rowers in wool tunics haul on long oars aboard a longship "
            "crossing a grey northern sea. In the foreground, a coil of rope and a round wooden shield rest on the deck; "
            "in the middle ground the striped sail billows; far behind, a faint coastline. Silver mist drifts in layers "
            "with soft light through the haze. A raven released from the bow flies ahead as if guiding the ship.\""
        )
    else:
        body = (
            "- ใส่ฉากหน้าและฉากหลังพอสังเขป และของประกอบ 1-2 อย่างที่เกี่ยวกับข้อเท็จจริงของฉากนั้น\n"
            "- ระบุแสงหรือบรรยากาศสั้นๆ 1 อย่าง\n"
            "- จุดโฟกัสหลักต้องชัดเจน ไม่ให้ภาพรก"
        )
    tail = (
        "\n- IDENTITY LOCK ใช้กับกลุ่มคนหรือกลุ่มสัตว์ได้ด้วย เช่น IDENTITY LOCK: [Viking rowers: bearded men in wool tunics, "
        "round wooden shields, braided hair] ถ้ากลุ่มนั้นปรากฏหลายฉาก ให้คัดลอกข้อความเดิมคำต่อคำเพื่อให้หน้าตาและชุดคงที่ทั้งคลิป\n"
        "- ห้ามมีตัวหนังสือ ตัวเลข เครื่องหมายคำพูด บอลลูนคำพูด หรือข้อความใดๆ ในภาพ ป้าย ใบเรือ โล่ และผนังต้องเป็นพื้นผิวเปล่า"
    )
    return common_head + body + tail

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


ALL_VOICE_DIRECTIONS = ["curious", "informative", "excited", "mysterious", "emphatic", "warm"]
VOICE_GUIDE = {
    "curious": "ใช้ curious เมื่อชวนสงสัย",
    "informative": "informative เมื่ออธิบายข้อเท็จจริง",
    "excited": "excited เมื่อมีจุดน่าตื่นเต้น",
    "mysterious": "mysterious เมื่อสร้างความพิศวง",
    "emphatic": "emphatic เมื่อต้องเน้นประเด็นสำคัญ",
    "warm": "warm เมื่อต้องการความอบอุ่น",
}


def enabled_voice_directions() -> list[str]:
    """อารมณ์ที่เปิดใช้ (ปรับด้วย VOICE_DIRECTIONS_ENABLED) informative เปิดอยู่เสมอเพราะเป็นค่าสำรอง"""
    raw = [x.strip().lower() for x in os.getenv("VOICE_DIRECTIONS_ENABLED", "").split(",") if x.strip()]
    chosen = [d for d in ALL_VOICE_DIRECTIONS if d in raw] if raw else list(ALL_VOICE_DIRECTIONS)
    if "informative" not in chosen:
        chosen.append("informative")
    return chosen


ENABLED_DIRECTIONS = enabled_voice_directions()
VOICE_DIRECTIONS = set(ENABLED_DIRECTIONS)


def voice_prompt_lines() -> tuple[str, str, str]:
    """คืน (รายการค่าที่เลือกได้, คำอธิบายการใช้, บรรทัดแนวทางลำดับอารมณ์ (อาจว่าง))"""
    names = ", ".join(ENABLED_DIRECTIONS)
    guide = ", ".join(VOICE_GUIDE[d] for d in ENABLED_DIRECTIONS)
    opening = [d for d in ("curious", "excited") if d in VOICE_DIRECTIONS]
    closing = [d for d in ("warm", "emphatic") if d in VOICE_DIRECTIONS]
    arc = ""
    if opening and closing:
        arc = (
            f"- แนวทางลำดับอารมณ์ (เป็นคำแนะนำเบาๆ ให้ยึดเนื้อหาจริงเป็นหลัก): ฉากแรกมักเป็น {' หรือ '.join(opening)} "
            f"และฉากสุดท้ายมักเป็น {' หรือ '.join(closing)}\n"
        )
    return names, guide, arc


PROMPT = """คุณเป็นนักเขียนบทคลิปสั้น "ความรู้แปลกๆ ที่คนส่วนใหญ่ไม่รู้" ภาษาไทย
หัวข้อที่ใช้ไปแล้ว (ห้ามซ้ำหรือใกล้เคียง):
{history}

หมวดของวันนี้ (ให้เลือกหัวข้อใหม่จากหมวดนี้): {category}

เงื่อนไข:
- เลือกข้อเท็จจริงที่ตรวจสอบได้จริงทางวิทยาศาสตร์ ประวัติศาสตร์ ธรรมชาติ หรือจิตวิทยา ห้ามแต่งหรือเดา ถ้าไม่มั่นใจให้เลือกเรื่องอื่น
- เปิดด้วยประโยคดึงความสนใจใน 1-2 ประโยคแรก และปิดด้วยประโยคสรุปสั้นๆ ที่น่าจดจำ
- น้ำเสียงบทโดยรวมเป็นมิตร น่าเชื่อถือ และเล่าอย่างเป็นธรรมชาติ เหมาะกับคลิปความรู้สั้น
- กำหนด voice_direction ให้ทุกฉากตามอารมณ์ของเนื้อหา เลือกได้เฉพาะ: {voice_names}
- {voice_guide}
{voice_arc}- อารมณ์ต้องพอดี ไม่เล่นใหญ่ และเปลี่ยนตามเนื้อหาแต่ละฉาก ไม่จำเป็นต้องเปลี่ยนอารมณ์ทุกฉาก
- บทพากย์รวมกัน {min_c}-{max_c} ตัวอักษร แบ่งเป็น {min_s}-{max_s} ฉาก
{kw_rule}- แต่ละฉากมี image_prompt เป็นภาษาอังกฤษ บรรยายภาพเดียวที่มีจุดโฟกัสหลักชัดเจน เป็นภาพแนวตั้ง (9:16) ตามกฎ image_prompt ด้านล่าง
- ความหลากหลายของภาพ: เลือกสิ่งที่เหมาะกับ narration ของแต่ละฉากจริง ๆ ทั้งสัตว์ สิ่งของ บุคคล สถานที่ ธรรมชาติ ภูมิประเทศ และภาพตัดขวาง ไม่ใช้สัตว์หรือตัวละครเดิมเป็นภาพประกอบทุกฉากโดยไม่มีเหตุผล
- ความคงที่ของเอกลักษณ์ (Visual Consistency): อ่านบททั้งหมดก่อนแบ่งภาพ หากมีตัวละคร/สัตว์/วัตถุ "ตัวเดิม" ปรากฏซ้ำในหลายฉาก ต้องเป็นชนิด/ตัวเดียวกันและคงเอกลักษณ์เดิม เช่น สายพันธุ์ รูปร่าง สัดส่วน สี ลวดลาย จุดเด่น และเครื่องหมายเฉพาะ ห้ามเปลี่ยนเป็นสัตว์คนละชนิดหรือเปลี่ยนสี/ลายโดยไม่มีเหตุผล
- สำหรับทุกฉากที่มีตัวเดิม ให้ใส่ IDENTITY LOCK ไว้ใน image_prompt เป็น "บรรทัดแยกท้ายข้อความ" (ขึ้นบรรทัดใหม่ด้วยอักขระ \n ใน JSON) ในรูปแบบเป๊ะๆ: IDENTITY LOCK: [คำอธิบายภาษาอังกฤษ] โดยต้องครอบคำอธิบายด้วยวงเล็บเหลี่ยม [ ] เสมอ และห้ามใส่ [ ] ซ้อนข้างใน ห้ามใส่คำบรรยายฉากไว้ในวงเล็บเหลี่ยม คัดลอกคำอธิบายชุดเดิมแบบคำต่อคำทุกตัวอักษรในทุกฉากที่กล่าวถึงตัวนั้น ให้ขึ้นต้นด้วยชื่อสามัญที่ชัดเจนของชนิด/สายพันธุ์/ประเภท (เช่น "A European robin (Erithacus rubecula)" หรือ "A red-eared slider turtle") ตามด้วยสี ลวดลาย สัดส่วน และจุดเด่น ห้ามใช้คำกว้าง ๆ เช่น "a bird" หรือ "an animal" อย่างเดียว ตัวอย่าง image_prompt: "The robin sings on a mossy branch at dawn, wide shot.\nIDENTITY LOCK: [A European robin (Erithacus rubecula), orange-red face and breast, olive-brown back, white belly, small round body, thin dark legs]"
- เปลี่ยนได้เฉพาะท่าทาง กิจกรรม สีหน้า มุมกล้อง และสภาพแวดล้อมตาม narration แต่ห้ามเปลี่ยนเอกลักษณ์หลัก หากฉากไม่ได้กล่าวถึงตัวเดิมก็ไม่ต้องใส่ตัวนั้น
- หากมีสัตว์ชนิดใหม่หรือตัวละครใหม่ ให้สร้าง IDENTITY LOCK ใหม่ของตัวนั้น ไม่เอาคำอธิบายของตัวก่อนหน้ามาใช้
- แต่ละฉากต้องบรรยายภาพให้ครบในตัวเอง โดยไม่ใช้คำว่า "same as previous image"; คัดลอกข้อความ IDENTITY LOCK ฉบับเต็มแทน (ภาพทั้งหมดจะเป็นการ์ตูนสีน้ำ)
- image_prompt ของแต่ละฉากต้องวาดสิ่งที่ narration ของฉากนั้นพูดถึงโดยตรง ห้ามเป็นภาพบรรยากาศทั่วไปที่ไม่เกี่ยวกับประโยคนั้น
- ถ้าสิ่งที่พูดถึงมองไม่เห็นจากภายนอก (เช่น ใต้ดิน ภายในร่างกาย จุลชีพ ใต้ทะเลลึก ภายในอะตอม) ให้ image_prompt เป็นภาพตัดขวางหรือภาพขยายใกล้ที่เห็นสิ่งนั้นชัดเจน ขึ้นต้นด้วยคำว่า cross-section cutaway view หรือ close-up macro view เช่น cross-section cutaway view of soil showing tree roots connected by thin glowing fungal threads
- ถ้าฉากเป็นภาพตัดขวาง/ภาพขยายใกล้ ให้บรรทัดแรกของ image_prompt ขึ้นต้นด้วย cross-section cutaway view หรือ close-up macro view แล้วค่อยมีบรรทัด IDENTITY LOCK ตามหลัง (ถ้ามี)
{image_rules}

ตอบเป็น JSON อย่างเดียว ไม่มีข้อความอื่น ตามรูปแบบ:
{{"topic": "หัวข้อสั้นๆ", "title": "ชื่อคลิป",
  "scenes": [{{"id": 1, "narration": "ข้อความพากย์", "voice_direction": "{voice_options}",{kw_field} "image_prompt": "..."}}]}}"""


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
                "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
            },
        },
    )
    check_status(f"gemini:{model}", r)
    cand = r.json()["candidates"][0]
    if cand.get("finishReason") == "MAX_TOKENS":
        print(f"WARNING: [gemini:{model}] คำตอบถูกตัดที่เพดานโทเคน ({GEMINI_MAX_OUTPUT_TOKENS}) JSON อาจไม่สมบูรณ์")
    return cand["content"]["parts"][0]["text"]


def call_groq(prompt: str, model: str) -> str:
    key = os.environ["GROQ_API_KEY"]
    body = {
        "model": model,
        "temperature": 0.9,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
        # โควตาฟรีของ Groq จำกัดโทเคน/นาทีต่ำ (~8K) จึงจำกัดการ "คิด" และความยาวคำตอบ
        "max_completion_tokens": GROQ_MAX_TOKENS,
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


GENERIC_IDENTITY_HEADS = {
    "bird", "animal", "creature", "character", "person", "man", "woman", "child", "boy", "girl",
    "insect", "bug", "fish", "plant", "tree", "flower", "thing", "object", "mammal", "reptile",
    "men", "women", "people", "persons", "children", "kids", "humans", "group", "crowd",
}


def identity_head(identity: str) -> str:
    """ชื่อชนิดช่วงต้นของ identity (ก่อนวงเล็บ/จุลภาค) ตัดคำนำหน้า a/an/the"""
    head = re.split(r"[(,;:]", identity, maxsplit=1)[0].strip().lower()
    return re.sub(r"^(a|an|the)\s+", "", head).strip()


def is_generic_head(head: str) -> bool:
    """True ถ้าชื่อชนิดกว้างเกินไป เช่น 'bird', 'small bird', 'bird with colorful feathers'"""
    words = head.split()
    if not words:
        return True
    if len(words) <= 2 and any(w in GENERIC_IDENTITY_HEADS for w in words):
        return True
    return words[0] in GENERIC_IDENTITY_HEADS and len(words) > 1 and words[1] in {"with", "that", "which", "having", "who"}


def check_identities(scenes: list) -> list[str]:
    """ตรวจ IDENTITY LOCK: รูปแบบ [..] ครบ ไม่เป็นคำกว้าง และตัวเดียวกันต้องมีข้อความเหมือนกันทุกฉาก"""
    errs = []
    seen: dict[str, tuple[int, str]] = {}
    for i, s in enumerate(scenes, 1):
        if not isinstance(s, dict):
            continue
        prompt = str(s.get("image_prompt", ""))
        if not re.search(r"IDENTITY\s+LOCK", prompt, re.I):
            continue
        if not re.search(r"IDENTITY\s+LOCK\s*:\s*\[[^\]\n]+\]", prompt, re.I):
            errs.append(f"ฉาก {i}: IDENTITY LOCK ต้องอยู่ในรูป IDENTITY LOCK: [คำอธิบาย] เป็นบรรทัดแยก")
            continue
        for ident in extract_identities(prompt):
            head = identity_head(ident)
            if len(ident) < 25 or is_generic_head(head):
                errs.append(f"ฉาก {i}: IDENTITY LOCK กว้างหรือสั้นเกินไป ('{ident[:40]}') ต้องขึ้นต้นด้วยชื่อชนิดที่ชัดเจน")
                continue
            if head in seen:
                first_scene, first_text = seen[head]
                if first_text != ident:
                    errs.append(f"ฉาก {i}: IDENTITY LOCK ของ '{head}' ไม่เหมือนฉาก {first_scene} (ต้องคัดลอกคำต่อคำ)")
            else:
                seen[head] = (i, ident)
    return errs


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
        img = str(s.get("image_prompt", "")).strip()
        if len(img) < 15:
            errs.append(f"ฉาก {i}: image_prompt สั้นเกินไป")
        else:
            # v3.8: นับคำของคำบรรยายฉาก (ไม่นับบรรทัด IDENTITY LOCK) ให้ได้ตามระดับ IMAGE_DETAIL_LEVEL
            words = len(strip_identity(img).split())
            if words < IMG_MIN_WORDS:
                errs.append(f"ฉาก {i}: image_prompt สั้นเกินไป ({words} คำ) ต้องบรรยายอย่างน้อย {IMG_MIN_WORDS} คำ (เป้า {IMG_ASK_MIN}-{IMG_ASK_MAX}) ตามกฎ image_prompt")
            elif words > IMG_MAX_WORDS:
                errs.append(f"ฉาก {i}: image_prompt ยาวเกินไป ({words} คำ) ต้องไม่เกิน {IMG_MAX_WORDS} คำ (เป้า {IMG_ASK_MIN}-{IMG_ASK_MAX})")
        direction = str(s.get("voice_direction", "")).strip().lower()
        if direction not in VOICE_DIRECTIONS:
            # ไม่ปฏิเสธทั้งบท (กันเสียโควตา retry) -> เติม informative แล้วเตือนใน log
            print(f"WARNING: ฉาก {i}: voice_direction '{direction}' ไม่ถูกต้องหรือหายไป -> ใช้ informative")
            direction = "informative"
        s["voice_direction"] = direction
        s["id"] = i
        if KEYWORDS_ENABLED:
            # v3.9: keywords ต้องเป็นข้อความที่อยู่ใน narration ตรงตัว ไม่ถูกต้อง -> ตัดคำนั้นทิ้ง + WARNING (ไม่ปฏิเสธทั้งบท)
            narr = str(s.get("narration", ""))
            raw_kws = s.get("keywords") or []
            if isinstance(raw_kws, str):
                raw_kws = [raw_kws]
            clean = []
            for k in raw_kws if isinstance(raw_kws, list) else []:
                k = str(k).strip()
                if 2 <= len(k) <= KEYWORD_MAX_CHARS and k in narr and k not in KEYWORD_STOPWORDS and k not in clean:
                    clean.append(k)
                else:
                    print(f"WARNING: ฉาก {i}: keyword '{k}' ไม่อยู่ใน narration ตรงตัว/ไม่เหมาะ -> ตัดทิ้ง")
            s["keywords"] = clean[:2]
    used_dirs = [s.get("voice_direction") for s in scenes if isinstance(s, dict) and s.get("voice_direction")]
    if len(used_dirs) >= 4 and len(set(used_dirs)) == 1:
        print(f"WARNING: ทุกฉากใช้อารมณ์เดียวกัน ({used_dirs[0]}) ตรวจว่าเหมาะกับเนื้อหาหรือไม่")
    errs.extend(check_identities(scenes))
    total = sum(len(str(s.get("narration", "")).strip()) for s in scenes if isinstance(s, dict))
    if not (MIN_CHARS <= total <= MAX_CHARS):
        errs.append(f"ความยาวบทรวม {total} ตัวอักษร ต้องอยู่ระหว่าง {MIN_CHARS}-{MAX_CHARS}")
    return errs


def with_feedback(prompt: str, errs: list[str]) -> str:
    """ถ้ารอบก่อนไม่ผ่าน ให้ต่อท้าย prompt ด้วยรายการข้อผิดพลาด เพื่อให้โมเดลแก้ตรงจุด (ไม่ใช่ส่งซ้ำเฉยๆ)"""
    if not errs:
        return prompt
    lines = "\n".join(f"- {e}" for e in errs[:8])
    return (
        prompt
        + "\n\nคำตอบรอบก่อนไม่ผ่านการตรวจด้วยเหตุผลต่อไปนี้ แก้ให้ครบทุกข้อ แล้วตอบเป็น JSON ฉบับสมบูรณ์ใหม่ทั้งหมด:\n"
        + lines
    )


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
        voice_names=voice_prompt_lines()[0],
        voice_guide=voice_prompt_lines()[1],
        voice_arc=voice_prompt_lines()[2],
        voice_options="|".join(ENABLED_DIRECTIONS),
        image_rules=image_rules(),
        kw_rule=keyword_prompt_parts()[0],
        kw_field=keyword_prompt_parts()[1],
    )
    print(f"หมวดประจำวัน: {todays_category()} | ระดับรายละเอียดภาพ: {IMAGE_DETAIL_LEVEL}")

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
        last_errs: list[str] = []  # ข้อผิดพลาดรอบก่อน ส่งกลับให้โมเดลแก้ (v3.6) รีเซ็ตเมื่อเปลี่ยนโมเดล
        for attempt in range(1, 4):
            try:
                raw = fn(with_feedback(prompt, last_errs), model)
                try:
                    data = parse(raw)
                except json.JSONDecodeError as je:
                    last_errs = [f"คำตอบไม่ใช่ JSON ที่ถูกต้อง ({je.msg}) ต้องตอบเป็น JSON อย่างเดียว"]
                    raise
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
                last_errs = errs
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
