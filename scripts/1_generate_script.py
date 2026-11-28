"""ขั้น 1: สร้างบทความรู้แปลกๆ + แบ่งฉาก -> output/script.json

ผู้ให้บริการ: Gemini (หลัก, ลองหลายรุ่นตามลำดับ) -> Groq (สำรอง) ทั้งคู่มี free tier
Secrets: GEMINI_API_KEY (จำเป็น), GROQ_API_KEY (แนะนำเป็นตัวสำรอง)
ตัวแปร env ที่ปรับได้:
  - GEMINI_MODEL            (ค่าเริ่มต้น: gemini-3.8-flash)
  - GEMINI_FALLBACK_MODELS  (ค่าเริ่มต้น: gemini-3.6-flash,gemini-3.5-flash-lite  คั่นด้วยจุลภาค)
  - GROQ_MODEL              (ค่าเริ่มต้น: openai/gpt-oss-120b)
  - SCRIPT_MIN_CHARS / SCRIPT_MAX_CHARS  (ค่าเริ่มต้นในโค้ดและ workflow: 520 / 900 ตัวอักษรของบทพากย์รวม)
  - CHARACTERS_ENABLED      (ค่าเริ่มต้น: 1; v4.7) เปิด/ปิดตัวละครประจำคลิป OZONE + ORBI (ปิด = ไม่ขอฟิลด์ characters และไม่ส่งภาพอ้างอิง)
  - HOOK_MAX_CHARS         (ค่าเริ่มต้น: 60; v4.8) ความยาวสูงสุดของคำถามฮุกในฉากที่ 1 (ราว 4-5 วินาที)
  - IMAGE_DETAIL_LEVEL      (ค่าเริ่มต้น: rich; ใช้ standard ถ้าภาพแน่นเกิน) กำหนดความละเอียดของ image_prompt และสไตล์ภาพ
  - SUBTITLES_ENABLED / SUBTITLE_KEYWORDS_ENABLED  (ค่าเริ่มต้น 1/1; ปิดอย่างใดอย่างหนึ่ง = ไม่ขอ keywords สำหรับซับสีเหลืองจาก AI)
  - GEMINI_MAX_OUTPUT_TOKENS / GROQ_MAX_TOKENS  (ค่าเริ่มต้น: 16384 / 6000) เพดานโทเคนคำตอบ กัน JSON ถูกตัด

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

from style import (
    CHARACTERS, CHARACTERS_ENABLED, PLACEMENTS, BOTTOM_RIGHT_RE, normalize_placement, IMAGE_DETAIL_LEVEL, coerce_bool, extract_identities, has_face_words,
    normalize_characters, raw_character_items, strip_identity,
)
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

# เสียงไทยพูดประมาณ 13-16 ตัวอักษร/วินาที (ค่าจริงวัดในขั้น 2 แล้วค่อยปรับ)
# ค่าเริ่มต้นในโค้ด 520-900 ตรงกับที่ workflow ตั้งไว้ ถ้าต้องการคลิปยาวขึ้นให้เพิ่ม SCRIPT_MAX_CHARS ใน workflow
MIN_CHARS = int(os.getenv("SCRIPT_MIN_CHARS", "520"))
HOOK_MAX_CHARS = int(os.getenv("HOOK_MAX_CHARS", "60"))  # v4.8: ความยาวสูงสุดของคำถามฮุก (ฉากที่ 1) ราว 4-5 วินาที
MAX_CHARS = int(os.getenv("SCRIPT_MAX_CHARS", "900"))
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


def character_prompt_parts() -> tuple[str, str]:
    """(v4.7) คืน (กฎตัวละครใน PROMPT, ฟิลด์ใน JSON ตัวอย่าง) ว่างทั้งคู่ถ้าปิด CHARACTERS_ENABLED"""
    if not CHARACTERS_ENABLED:
        return "", ""
    o, r = CHARACTERS["ozone"]["name"], CHARACTERS["robot"]["name"]
    rule = (
        f"- ตัวละครประจำคลิป: {o} (เด็กชายนักสำรวจชุดอวกาศผู้ช่างสงสัย) และ {r} (หุ่นยนต์ลอยตัวกลมคู่ใจของ {o}) "
        "ระบบแนบภาพอ้างอิงและใส่รูปลักษณ์ของทั้งสองให้เองทุกครั้ง ทุกฉากต้องมีฟิลด์ characters เป็นลิสต์ของรหัส \"ozone\" และ/หรือ \"robot\" (ฉากที่ไม่มีตัวละคร = [])\n"
        "- สัดส่วนตัวละคร: ใส่ตัวละครราวครึ่งหนึ่งของฉาก เน้นฉากแรก ฉากเปลี่ยนประเด็น และฉากจบ ฉากที่ต้องโชว์ข้อเท็จจริงล้วนๆ "
        "(ภาพตัดขวาง ภาพขยายใกล้ จำนวน/ขนาด/สัดส่วน) ให้เป็น [] หรือให้ตัวละครตัวเล็กอยู่ริมภาพโดยไม่บังจุดโฟกัส "
        "ต้องมีอย่างน้อย 2 ฉากที่มีตัวละคร และอย่างน้อย 2 ฉากที่ไม่มี\n"
        f"- ในฉากที่มีตัวละคร image_prompt ต้องเรียกชื่อ {o} และ/หรือ {r} ตรงๆ แล้วออกแบบท่าทาง การกระทำ สีหน้า และตำแหน่งในภาพให้เข้ากับอารมณ์และเนื้อหา narration ของฉากนั้นเอง "
        "(เช่น ตื่นเต้น ประหลาดใจ สงสัย ครุ่นคิด ดีใจ กังวล) เปลี่ยนไปตามฉาก ไม่ใช้ท่าเดิมซ้ำทุกฉาก และตัวละครต้องมองหรือชี้สิ่งที่ narration พูดถึง\n"
        f"- ห้ามบรรยายหน้าตา ผม ชุด สี หรือรูปร่างของ {o} และ {r} (ระบบใส่ให้แล้ว) ห้ามใส่ IDENTITY LOCK ให้สองตัวนี้ (สัตว์หรือตัวอื่นในฉากยังใช้ IDENTITY LOCK ตามกฎเดิม) "
        f"เรียก {r} ด้วยชื่อ {r} เท่านั้น ไม่ใช้คำว่า robot ใน image_prompt\n"
        f"- สีหน้าของ {r} แสดงบนหน้าจอสีดำ ให้เขียนเป็น \"{r}'s screen shows ...\" เช่น happy closed-arc eyes, sparkling star eyes, wide round surprised eyes, worried eyes, sleepy eyes "
        f"และ {r} ลอยอยู่กลางอากาศ ไม่มีขา\n"
        f"- ตัวละครห้ามเพิ่มข้อเท็จจริง วัตถุ เหตุการณ์ เครื่องมือ หรือเปลี่ยนชุดที่ narration ไม่ได้พูดถึง ห้ามบังจุดโฟกัสของข้อเท็จจริง "
        "narration ยังเป็นเสียงผู้บรรยายคนเดียว ห้ามเขียนเป็นบทสนทนาหรือให้ตัวละครพูด และ ORBI ไม่มีบทพูดหรือฉากปฏิกิริยาแยก "
        "(แสดงอารมณ์ผ่านสีหน้าบนหน้าจอเท่านั้น)\n"
        "- ตำแหน่งตัวละคร: ทุกฉากที่มีตัวละครต้องมีฟิลด์ placement เลือก 1 ค่า: "
        "\"hero_center\" (ใช้เฉพาะฉากที่ 1: ตัวละครใหญ่ ใกล้กล้อง เห็นหน้าชัด อยู่กลางภาพได้), "
        "\"left_edge\" (ขอบซ้าย ช่วงบนหรือกลาง), \"right_edge\" (ขอบขวา ช่วงบนหรือกลาง), "
        "\"top_peek\" (โผล่จากขอบบน เห็นครึ่งบนและหน้า), \"bottom_left\" (มุมซ้ายล่างเหนือพื้นที่ซับ ตัวเล็ก) "
        "ห้ามเลือกตำแหน่งเดียวกับฉากก่อนหน้าที่มีตัวละคร และต้องเลือกให้ไม่บังจุดโฟกัสของข้อเท็จจริง "
        "ตัวละครโผล่มาครึ่งตัวหรือถูกขอบภาพตัดได้ตามเนื้อหา ถ้าเลือกตำแหน่งขอบ ให้เขียนใน image_prompt ด้วยว่าตัวละครอยู่ตำแหน่งนั้นและถูกเฟรมตัดอย่างไร "
        "(เช่น \"ORBI peeks in from the top edge, upper half visible, cropped by the frame\") และจุดโฟกัสของข้อเท็จจริงต้องอยู่ฝั่งตรงข้ามหรือกลางภาพ "
        "ห้ามวางตัวละครที่มุมขวาล่างทุกกรณี (เป็นที่ของปุ่มแพลตฟอร์ม) และห้ามเขียนคำว่า bottom right / lower right ใน image_prompt ขอบล่างต้องโล่งสำหรับซับ\n"
    )
    return rule, ' "characters": ["ozone", "robot"], "placement": "hero_center",'


def image_rules() -> str:
    """กฎการเขียน image_prompt ตามระดับ IMAGE_DETAIL_LEVEL (ใส่ลงใน PROMPT)"""
    common_head = (
        f"- image_prompt เขียนเป็นภาษาอังกฤษ ความยาว {IMG_ASK_MIN}-{IMG_ASK_MAX} คำ (ไม่นับบรรทัด IDENTITY LOCK) "
        "เป็นประโยคบรรยายเชิงบวกว่า \"มีอะไรอยู่ในภาพ\" ห้ามใช้ negative prompt หรือคำปฏิเสธ เช่น no, without, not, avoid\n"
        "- ประโยคแรกของ image_prompt ต้องบอก \"ใคร/อะไร ทำอะไร ที่ไหน\" ให้ชัดก่อน (โมเดลภาพให้น้ำหนักช่วงต้นข้อความ) "
        "แล้วค่อยเพิ่มรายละเอียดตามลำดับ\n"
        "- ถ้า narration พูดถึงการกระทำของคนหรือสัตว์ ต้องเห็นตัวนั้นทำสิ่งนั้นจริงในภาพด้วยท่าทางที่ชัดเจน "
        "ห้ามวาดแค่ยานพาหนะ สิ่งของ หรือสถานที่เปล่าๆ (เช่น พูดถึงนักพายเรือ ต้องมีนักพายกำลังออกแรงดึงไม้พาย ไม่ใช่เรือเปล่า)\n"
        "- เลือกภาพที่อธิบายข้อเท็จจริงหลักของฉากได้ทันที: ระบุวัตถุ/ตัวละครหลัก การกระทำ ตำแหน่ง และความสัมพันธ์ระหว่างองค์ประกอบให้ชัด "
        "อย่าใส่รายละเอียดตกแต่งที่แย่งจุดสนใจหรือไม่ได้ช่วยอธิบาย narration\n"
        "- ถ้า narration มีจำนวน ขนาด ลำดับ หรือการเปรียบเทียบ ให้สื่อด้วยจำนวน/สัดส่วน/ตำแหน่งของวัตถุในภาพอย่างถูกต้อง "
        "ไม่ต้องสร้างตัวเลขหรือตัวหนังสือให้อ่านบนภาพ เพราะระบบภาพไม่ใช่ระบบทำอินโฟกราฟิก\n"
        "- ห้ามเพิ่มเหตุการณ์ วัตถุ เครื่องมือ เครื่องแต่งกาย หรือสิ่งมีชีวิตที่ไม่มีหลักฐานใน narration/ข้อเท็จจริงของฉาก "
        "หากไม่แน่ใจรายละเอียดทางกายวิภาคหรือประวัติศาสตร์ ให้ใช้ภาพที่เรียบง่ายและถูกต้องแทนการเดา\n"
    )
    if IMAGE_DETAIL_LEVEL == "rich":
        body = (
            "- แยกชั้นภาพให้ชัด: ฉากหน้า (foreground) ฉากกลาง (middle ground) และฉากหลัง (background)\n"
            "- ใส่ของประกอบ 2-3 อย่างที่เกี่ยวกับข้อเท็จจริงของฉากนั้น เช่น โล่ทรงกลม เชือก ธงใบเรือ\n"
            "- ระบุแสงและบรรยากาศ เช่น หมอกเทาเงินลอยเป็นชั้น แสงรำไรผ่านม่านหมอก\n"
            "- ถ้าจะใส่รายละเอียดเสริม 1 อย่างต่อฉาก ต้องเป็นสิ่งที่มีอยู่จริงและเกี่ยวกับข้อเท็จจริงนั้น วาดแบบสมจริง (เช่น ผลึก sunstone นกกาที่ปล่อยบินนำทาง) ห้ามสร้างวัตถุสัญลักษณ์เชิงจินตนาการที่ไม่มีอยู่จริง เช่น เฟือง นาฬิกาทราย กุญแจ ริบบิ้นวัด และห้ามทำให้สิ่งไม่มีชีวิตมีหน้าตาหรือชีวิต\n"
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
        "- IDENTITY LOCK ของสิ่งไม่มีชีวิต (เช่น อวัยวะ เซลล์ สิ่งของ) ให้บรรยายรูปทรง สี วัสดุ และลวดลายเท่านั้น ไม่ต้องเอ่ยถึงหน้าตา แขนขา หรือบุคลิกตัวการ์ตูนเลย\n"
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


PROMPT = """คุณเป็นนักเขียนบทคลิปสั้น "ความรู้แปลกๆ ที่คนส่วนใหญ่ไม่รู้" ภาษาไทย
หัวข้อที่ใช้ไปแล้ว (ห้ามซ้ำหรือใกล้เคียง):
{history}

หมวดของวันนี้ (ให้เลือกหัวข้อใหม่จากหมวดนี้): {category}

เงื่อนไข:
- เลือกข้อเท็จจริงที่ตรวจสอบได้จริงทางวิทยาศาสตร์ ประวัติศาสตร์ ธรรมชาติ หรือจิตวิทยา ห้ามแต่งหรือเดา ถ้าไม่มั่นใจให้เลือกเรื่องอื่น
- ความแม่นยำสำคัญกว่าความหวือหวา: ห้ามสร้างตัวเลข สถิติ วันที่ ชื่อบุคคล กลไก หรือคำพูดอ้างอิงขึ้นเอง; หากข้อมูลเป็นค่าประมาณ/ยังมีข้อถกเถียง ให้ใช้ถ้อยคำบอกระดับความไม่แน่นอนอย่างตรงไปตรงมา หรือเลือกข้อเท็จจริงอื่นที่ชัดเจนกว่า
- อย่าขยายข้อเท็จจริงให้เกินหลักฐาน และอย่าใช้คำว่า “ทุก”, “เสมอ”, “ไม่มีทาง” หรือคำยืนยันเด็ดขาด หากข้อเท็จจริงมีข้อยกเว้น
- เพิ่ม source_hint เป็นลิสต์ชื่อแหล่งข้อมูล/หน่วยงานที่น่าเชื่อถือ 2-4 แห่งที่เกี่ยวข้องกับข้อเท็จจริงสำคัญ เพื่อใช้ตรวจสอบภายหลัง ห้ามแต่ง URL หรืออ้างว่าได้เปิดอ่านแหล่งข้อมูลแล้ว
- โครงเรื่องต้องมีการเดินหน้า ไม่ใช่การเรียงเกร็ดที่ไม่เกี่ยวกัน: เปิดด้วยข้อเท็จจริง/คำถามที่น่าทึ่งที่สุด, อธิบายว่าทำไมเรื่องนี้จึงเกิดขึ้น, ค่อยๆ เปิดเผยรายละเอียดหรือผลที่ตามมา แล้วปิดด้วยข้อสรุปที่ทำให้ผู้ชมเข้าใจเรื่องได้ครบ
- ฉากที่ 1 ต้องเป็น HOOK ทันที: เป็น “คำถามสั้นๆ” ที่เฉพาะเจาะจง น่าติดตาม และชวนอยากรู้คำตอบ (ไม่เกิน {hook_max} ตัวอักษร ลงท้ายด้วย ? หรือคำถามภาษาไทย เช่น ไหม ทำไม อะไร กี่) ไม่ทักทาย ไม่แนะนำตัว ไม่พูดว่า “วันนี้เราจะมา...” ไม่เกริ่นนำยาว และห้ามมีข้อมูลผิดแฝงในคำถาม ต้องตอบได้จริงด้วยข้อเท็จจริงในฉากถัดไป ฉากที่ 1 เป็นข้อยกเว้นของกฎ “ทุกฉากต้องเพิ่มข้อเท็จจริงใหม่” ได้ เพราะเป็นคำถามเปิด
- ฉากที่ 2 ต้องเริ่มตอบคำถามของ HOOK ทันที แล้วขยายบริบทและทยอยให้คำตอบอย่างมีลำดับ แต่ห้ามจงใจปิดบังข้อมูลสำคัญจนทำให้เข้าใจผิด
- ทุกฉาก (ยกเว้นฉากที่ 1 ที่เป็นคำถามเปิด) ต้องเพิ่มข้อเท็จจริง มุมอธิบาย ตัวอย่าง หรือผลลัพธ์ใหม่ที่จำเป็นต่อเรื่อง หากตัดฉากนั้นออกแล้วใจความไม่เปลี่ยน ให้รวม/ตัดเนื้อหาซ้ำแทนการยืดบท
- เชื่อมฉากด้วยเหตุและผลหรือคำถามที่ฉากถัดไปตอบได้ ใช้คำเชื่อมเป็นธรรมชาติ ไม่ต้องลงท้ายทุกฉากด้วย cliffhanger หรือคำถาม
- ตอนจบต้องตอบหรือคลี่คลายประเด็นที่เปิดไว้ และทิ้งข้อคิด/ภาพจำสั้นๆ ที่เกี่ยวข้องกับเรื่อง ห้ามจบด้วย CTA บังคับหรือคำชวนกดติดตามที่ไม่จำเป็น
- ใน narration ให้เขียนตัวเลขทศนิยม หน่วย และตัวย่อวิทยาศาสตร์เป็นคำอ่านภาษาไทยที่ TTS อ่านได้เป็นธรรมชาติ เช่น 37.2 เป็น “สามสิบเจ็ดจุดสอง” และ CO₂ เป็น “คาร์บอนไดออกไซด์”; คงรูปแบบตัวเลขใน image_prompt ได้ตามความเหมาะสม
- ใช้ภาษาไทยแบบพูดจริง กระชับ ชัดเจน เป็นมิตรและน่าเชื่อถือ เลี่ยงภาษาราชการ คำฟุ่มเฟือย คำซ้ำ และประโยคซ้อนยาว; อ่านออกเสียงแล้วต้องลื่นไหล ไม่เหมือนอ่านข้อความจากบทความ
- ไม่ใช้ clickbait ที่เกินจริง: HOOK ต้องน่าสนใจแต่เนื้อหาที่ตามมาต้องพิสูจน์/อธิบายสิ่งที่เปิดไว้ได้จริง
- น้ำเสียงบทโดยรวมเป็นมิตร น่าเชื่อถือ และเล่าอย่างเป็นธรรมชาติ เหมาะกับคลิปความรู้สั้น
- บทพากย์รวมกัน {min_c}-{max_c} ตัวอักษร แบ่งเป็น {min_s}-{max_s} ฉาก
{kw_rule}- แต่ละฉากมี image_prompt เป็นภาษาอังกฤษ บรรยายภาพเดียวที่มีจุดโฟกัสหลักชัดเจน เป็นภาพแนวตั้ง (9:16) ตามกฎ image_prompt ด้านล่าง
- จับคู่ภาพกับ narration แบบตรงประเด็น: ภาพต้องแสดงสิ่งที่กำลังพูดถึงในฉากนั้น ไม่ใช่เพียงภาพสวยหรือภาพบรรยากาศของหัวข้อโดยรวม และห้ามใส่ข้อมูลภาพที่ขัดกับ narration
- แต่ละฉากควรมีองค์ประกอบหลักที่แตกต่างตามเนื้อหา แต่ยังรักษาเอกลักษณ์ตัวละครและสไตล์เดิม ห้ามเปลี่ยนมุมภาพเพียงเพื่อความหลากหลายจนทำให้ความหมายคลาดเคลื่อน
- ความหลากหลายของภาพ: เลือกสิ่งที่เหมาะกับ narration ของแต่ละฉากจริง ๆ ทั้งสัตว์ สิ่งของ บุคคล สถานที่ ธรรมชาติ ภูมิประเทศ และภาพตัดขวาง ไม่ใช้สัตว์หรือตัวละครเดิมเป็นภาพประกอบทุกฉากโดยไม่มีเหตุผล
- สไตล์ภาพ (สำคัญมาก): ทุกฉากใช้สไตล์เดียวกันคือสีน้ำนิทานโทนพาสเทล รูปทรงกลมมน เรียบง่าย แสงนุ่ม ระบบภาพใส่สไตล์นี้ให้เองแล้ว ให้ระบุ has_living ทุกฉาก: true ถ้าในภาพมีคน สัตว์ แมลง หรือสิ่งมีชีวิตขนาดเล็กอย่างน้อยหนึ่งตัว (ระบบจะวาดเป็นตัวละคร kawaii chibi) และ false ถ้าภาพไม่มีสิ่งมีชีวิตเลย (วัตถุ สถานที่ ปรากฏการณ์ ดวงดาว เซลล์ อวัยวะ โมเลกุล ภาพตัดขวาง) ความน่ารักของสิ่งไม่มีชีวิตต้องมาจากรูปทรงและสี เช่น \"soft rounded plush-like shape in pastel colors with tiny sparkles of light\" และห้ามเอ่ยถึง eyes, face, mouth, cheeks, smile, arms, legs หรือ kawaii, chibi, cute ใน image_prompt ของฉากที่ has_living เป็น false เลย แม้เป็นประโยคปฏิเสธ (โมเดลภาพไม่มี negative prompt การสั่งห้ามหน้าตากลับดึงหน้าตาเข้ามาในภาพ) ฉากที่มีทั้งสิ่งมีชีวิตและวัตถุ (has_living เป็น true) ให้เฉพาะตัวละครที่มีชีวิตมีหน้าตา ส่วนวัตถุรอบข้างให้บรรยายเป็นรูปทรงกลมมนเรียบๆ ไม่มีหน้าตา ข้อเท็จจริงทางวิทยาศาสตร์และประวัติศาสตร์ในภาพต้องยังถูกต้อง
- ความคงที่ของเอกลักษณ์ (Visual Consistency): อ่านบททั้งหมดก่อนแบ่งภาพ หากมีตัวละคร/สัตว์/วัตถุ "ตัวเดิม" ปรากฏซ้ำในหลายฉาก ต้องเป็นชนิด/ตัวเดียวกันและคงเอกลักษณ์เดิม เช่น สายพันธุ์ รูปร่าง สัดส่วน สี ลวดลาย จุดเด่น และเครื่องหมายเฉพาะ ห้ามเปลี่ยนเป็นสัตว์คนละชนิดหรือเปลี่ยนสี/ลายโดยไม่มีเหตุผล
- สำหรับทุกฉากที่มีตัวเดิม ให้ใส่ IDENTITY LOCK ไว้ใน image_prompt เป็น "บรรทัดแยกท้ายข้อความ" (ขึ้นบรรทัดใหม่ด้วยอักขระ \n ใน JSON) ในรูปแบบเป๊ะๆ: IDENTITY LOCK: [คำอธิบายภาษาอังกฤษ] โดยต้องครอบคำอธิบายด้วยวงเล็บเหลี่ยม [ ] เสมอ และห้ามใส่ [ ] ซ้อนข้างใน ห้ามใส่คำบรรยายฉากไว้ในวงเล็บเหลี่ยม คัดลอกคำอธิบายชุดเดิมแบบคำต่อคำทุกตัวอักษรในทุกฉากที่กล่าวถึงตัวนั้น ให้ขึ้นต้นด้วยชื่อสามัญที่ชัดเจนของชนิด/สายพันธุ์/ประเภท (เช่น "A European robin (Erithacus rubecula)" หรือ "A red-eared slider turtle") ตามด้วยสี ลวดลาย สัดส่วน และจุดเด่น ห้ามใช้คำกว้าง ๆ เช่น "a bird" หรือ "an animal" อย่างเดียว ตัวอย่าง image_prompt: "The robin sings on a mossy branch at dawn, wide shot.\nIDENTITY LOCK: [A European robin (Erithacus rubecula), orange-red face and breast, olive-brown back, white belly, small round body, thin dark legs]"
- เปลี่ยนได้เฉพาะท่าทาง กิจกรรม สีหน้า มุมกล้อง และสภาพแวดล้อมตาม narration แต่ห้ามเปลี่ยนเอกลักษณ์หลัก หากฉากไม่ได้กล่าวถึงตัวเดิมก็ไม่ต้องใส่ตัวนั้น
- หากมีสัตว์ชนิดใหม่หรือตัวละครใหม่ ให้สร้าง IDENTITY LOCK ใหม่ของตัวนั้น ไม่เอาคำอธิบายของตัวก่อนหน้ามาใช้
- แต่ละฉากต้องบรรยายภาพให้ครบในตัวเอง โดยไม่ใช้คำว่า "same as previous image"; คัดลอกข้อความ IDENTITY LOCK ฉบับเต็มแทน (ภาพเป็นสีน้ำนิทานโทนพาสเทลตามกฎ "สไตล์ภาพ" ด้านบน)
- image_prompt ของแต่ละฉากต้องวาดสิ่งที่ narration ของฉากนั้นพูดถึงโดยตรงและตรงตามรายละเอียดที่พูด ห้ามเป็นภาพบรรยากาศทั่วไป เช่น ถ้า narration พูดถึงลักษณะของดวงจันทร์ (หลุมบนพื้นผิว เฟสของดวงจันทร์ สี ตำแหน่งบนท้องฟ้า) ภาพต้องแสดงหลุม เฟส สี และตำแหน่งนั้นจริง จำนวน ขนาด สัดส่วน สี ตำแหน่ง และลำดับเหตุการณ์ที่ narration พูดต้องสื่อให้เห็นผ่านองค์ประกอบภาพอย่างถูกต้อง แต่ห้ามสร้างตัวหนังสือ/ตัวเลข/ป้ายกำกับบนภาพ
- ถ้าสิ่งที่พูดถึงมองไม่เห็นจากภายนอก (เช่น ใต้ดิน ภายในร่างกาย จุลชีพ ใต้ทะเลลึก ภายในอะตอม) ให้ image_prompt เป็นภาพตัดขวางหรือภาพขยายใกล้ที่เห็นสิ่งนั้นชัดเจน ขึ้นต้นด้วยคำว่า cross-section cutaway view หรือ close-up macro view เช่น cross-section cutaway view of soil showing tree roots connected by thin glowing fungal threads
- ถ้าฉากเป็นภาพตัดขวาง/ภาพขยายใกล้ ให้บรรทัดแรกของ image_prompt ขึ้นต้นด้วย cross-section cutaway view หรือ close-up macro view แล้วค่อยมีบรรทัด IDENTITY LOCK ตามหลัง (ถ้ามี)
{char_rule}{image_rules}

ตอบเป็น JSON อย่างเดียว ไม่มีข้อความอื่น ตามรูปแบบ:
{{"topic": "หัวข้อสั้นๆ", "title": "ชื่อคลิป", "source_hint": ["ชื่อหน่วยงานหรือแหล่งข้อมูล"],
  "scenes": [{{"id": 1, "narration": "ข้อความพากย์",{kw_field} "has_living": true,{char_field} "image_prompt": "..."}}]}}"""


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
                "temperature": float(os.getenv("SCRIPT_TEMPERATURE", "0.65")),
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
        "temperature": float(os.getenv("SCRIPT_TEMPERATURE", "0.65")),
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


# v4.2: IDENTITY LOCK ของสิ่งไม่มีชีวิตห้ามมีหน้าตา/แขนขา (ถ้าพบ -> ให้ AI เขียนบทใหม่ผ่านระบบ retry เดิม)
NONLIVING_HEAD_WORDS = {
    "brain", "cell", "cells", "neuron", "neurons", "molecule", "molecules", "atom", "atoms", "protein", "organ",
    "heart", "lung", "lungs", "kidney", "liver", "stomach", "moon", "sun", "planet", "star", "cloud", "rock",
    "crystal", "mineral", "machine", "robot", "tool", "building", "house", "car", "ship", "boat", "cup", "mug",
    "clock", "book", "key", "gear", "droplet", "drop", "wave", "mountain", "volcano", "tower", "bridge",
    "map", "bicycle", "bike", "train", "watch", "earth", "comet", "galaxy",
}
_NL_ALT = "|".join(sorted((re.escape(w) for w in NONLIVING_HEAD_WORDS), key=len, reverse=True))
_FACE_ALT = r"(?:eyes?|eyelashes|cheeks?|mouths?|smil\w*|grin\w*|lips|arms?|legs?|faces?|facial)"
# v4.4: ฉากที่มีสิ่งมีชีวิต (has_living=true) ตัวละครมีหน้าตาได้ แต่ถ้าประโยคเดียวกันผูกหน้าตาเข้ากับวัตถุ -> ปฏิเสธ
# (heuristic: "<วัตถุ> with ... eyes", "<วัตถุ>'s face", "smiling <วัตถุ>")
_OBJECT_FACE_RES = [
    re.compile(rf"\b(?:{_NL_ALT})s?\b(?:\W+\w+){{0,4}}?\W+(?:with|has|have|having|showing)\W+(?:\w+\W+){{0,3}}?{_FACE_ALT}\b", re.I),
    re.compile(rf"\b(?:{_NL_ALT})s?'s?\s+{_FACE_ALT}\b", re.I),
    re.compile(rf"\b(?:smiling|grinning|winking|happy|cute)\s+(?:\w+\s+)?(?:{_NL_ALT})s?\b", re.I),
]


def nonliving_with_face(ident: str) -> bool:
    head_words = set(identity_head(ident).replace("-", " ").split())
    return bool(head_words & NONLIVING_HEAD_WORDS) and has_face_words(ident)


def object_with_face(text: str) -> bool:
    """ฉากมีสิ่งมีชีวิต: True ถ้าประโยคใดผูกหน้าตา/แขนขาเข้ากับวัตถุไม่มีชีวิต"""
    for sentence in re.split(r"[.;!?,\n]+", str(text)):  # v4.7: ตัดที่จุลภาคด้วย กัน "moon with craters, eyes wide" ถูกอ่านเป็นดวงจันทร์มีตา
        if any(rx.search(sentence) for rx in _OBJECT_FACE_RES):
            return True
    return False


def check_scene_faces(i: int, s: dict, has_living: bool) -> list[str]:
    """v4.4: ตรวจ image_prompt ทั้งฉาก (รวมบรรทัด IDENTITY LOCK) ไม่ให้วัตถุไม่มีชีวิตมีหน้าตา/แขนขา"""
    img = str(s.get("image_prompt", ""))
    if not has_living:
        if has_face_words(img):
            return [
                f"ฉาก {i}: has_living เป็น false แต่ image_prompt มีคำเกี่ยวกับหน้าตา/แขนขา/kawaii (eyes, face, mouth, cheeks, smile, arms, legs ฯลฯ) "
                "ให้เขียนใหม่โดยไม่เอ่ยถึงคำเหล่านี้เลย (แม้เป็นประโยคปฏิเสธ) บรรยายด้วยรูปทรงกลมมนนุ่ม สี พาสเทล และประกายแสงเล็กๆ แทน "
                "หรือถ้าในภาพมีสิ่งมีชีวิตจริงให้ตั้ง has_living เป็น true"
            ]
        return []
    if object_with_face(img):
        return [
            f"ฉาก {i}: image_prompt ทำให้วัตถุหรือสิ่งไม่มีชีวิตมีหน้าตา/แขนขา ให้เฉพาะตัวละครที่มีชีวิตมีหน้าตา "
            "ส่วนวัตถุรอบข้างบรรยายเป็นรูปทรงกลมมนเรียบๆ ไม่เอ่ยถึงหน้าตา"
        ]
    return []


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
            if nonliving_with_face(ident):
                errs.append(f"ฉาก {i}: IDENTITY LOCK ของสิ่งไม่มีชีวิต ('{ident[:40]}') ห้ามมีตา แก้ม ปาก แขนขา หรือความน่ารัก ให้บรรยายรูปทรง สี วัสดุตามจริง")
                continue
            if head in seen:
                first_scene, first_text = seen[head]
                if first_text != ident:
                    errs.append(f"ฉาก {i}: IDENTITY LOCK ของ '{head}' ไม่เหมือนฉาก {first_scene} (ต้องคัดลอกคำต่อคำ)")
            else:
                seen[head] = (i, ident)
    return errs


def check_scene_characters(i: int, s: dict, img: str) -> list[str]:
    """(v4.7) ตรวจฟิลด์ characters ของฉาก; ตั้ง s["characters"] เป็นรหัสที่ถูกต้อง (ปิดระบบ = ลิสต์ว่าง)"""
    if not CHARACTERS_ENABLED:
        s["characters"] = []
        return []
    raw = raw_character_items(s.get("characters"))
    ids = normalize_characters(raw)
    errs = []
    unknown = [x for x in raw if x not in CHARACTERS]
    if unknown:
        errs.append(f"ฉาก {i}: characters มีรหัสที่ไม่รู้จัก {unknown} ใช้ได้เฉพาะ {list(CHARACTERS)} (ไม่มีตัวละคร = [])")
    s["characters"] = ids
    for cid in ids:
        name = CHARACTERS[cid]["name"]
        if not re.search(rf"\b{re.escape(name)}\b", img, re.I):
            errs.append(f"ฉาก {i}: characters มี '{cid}' แต่ image_prompt ไม่ได้เรียกชื่อ {name} ตรงๆ ให้เขียนท่าทาง สีหน้า ตำแหน่งของ {name} ในฉากนี้")
    if ids:
        banned = {"robot"} | {c["name"].lower() for c in CHARACTERS.values()}
        for ident in extract_identities(img):
            if banned & set(re.findall(r"[a-z]+", identity_head(ident))):
                errs.append(f"ฉาก {i}: ห้ามใส่ IDENTITY LOCK ของตัวละครประจำ ('{ident[:40]}') ระบบใส่รูปลักษณ์ให้เองจากภาพอ้างอิง")
    return errs


HOOK_QUESTION_RE = re.compile(r"[?？]|ไหม|หรือเปล่า|หรือไม่|อะไร|ทำไม|อย่างไร|ยังไง|เท่าไร|เท่าไหร่|ใคร|ที่ไหน|เมื่อไร|เมื่อไหร่|กี่|หรือ")
HOOK_GREETING_RE = re.compile(r"สวัสดี|ยินดีต้อนรับ|วันนี้เรา|วันนี้ผม|วันนี้เรามา|ยินดีที่ได้|ขอต้อนรับ")


def check_hook(scenes: list) -> list[str]:
    """(v4.8) ฉากที่ 1 ต้องเป็นคำถามสั้นๆ ไม่ทักทาย"""
    if not scenes or not isinstance(scenes[0], dict):
        return []
    text = str(scenes[0].get("narration", "")).strip()
    errs = []
    if HOOK_GREETING_RE.search(text):
        errs.append("ฉากที่ 1: ห้ามทักทายหรือแนะนำตัว ให้เปิดด้วยคำถามสั้นๆ ที่น่าติดตามทันที")
    if not HOOK_QUESTION_RE.search(text):
        errs.append("ฉากที่ 1: ต้องเป็นคำถามสั้นๆ (ลงท้ายด้วย ? หรือคำถามภาษาไทย เช่น ไหม ทำไม อะไร กี่)")
    if len(text) > HOOK_MAX_CHARS:
        errs.append(f"ฉากที่ 1: คำถามฮุกยาว {len(text)} ตัวอักษร ต้องไม่เกิน {HOOK_MAX_CHARS} ให้ตัดให้สั้นลง")
    return errs


def check_placements(scenes: list) -> list[str]:
    """(v4.8) ตรวจ placement: ค่าถูกต้อง, ฉากที่ 1 ต้องมีตัวละครแบบ hero_center, hero_center เฉพาะฉากที่ 1,
    ไม่ซ้ำกับฉากก่อนหน้าที่มีตัวละคร, image_prompt ไม่มีมุมขวาล่าง; ตั้ง s["placement"] เป็นค่าที่ถูกต้อง (ไม่มีตัวละคร = "")"""
    if not CHARACTERS_ENABLED:
        return []
    errs, prev = [], None
    for i, s in enumerate(scenes, 1):
        if not isinstance(s, dict):
            continue
        if not s.get("characters"):
            s["placement"] = ""
            if i == 1:
                errs.append("ฉากที่ 1: ต้องมีตัวละคร (OZONE เป็นผู้ถามฮุก) แบบ hero_center")
            continue
        raw = str(s.get("placement") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if raw not in PLACEMENTS:
            errs.append(f"ฉาก {i}: placement '{raw}' ไม่ถูกต้อง ใช้ได้เฉพาะ {list(PLACEMENTS)}")
        elif raw == "hero_center" and i != 1:
            errs.append(f"ฉาก {i}: hero_center ใช้ได้เฉพาะฉากที่ 1 ฉากนี้ให้เลือกตำแหน่งขอบอื่น")
        pl = normalize_placement(raw, i)
        s["placement"] = pl
        if i == 1 and pl != "hero_center":
            errs.append("ฉากที่ 1: ต้องมีตัวละครแบบ hero_center (ใหญ่ เห็นหน้าชัด)")
        if prev is not None and pl == prev:
            errs.append(f"ฉาก {i}: placement '{pl}' ซ้ำกับฉากก่อนหน้าที่มีตัวละคร ให้เลือกตำแหน่งอื่น")
        if BOTTOM_RIGHT_RE.search(str(s.get("image_prompt", ""))):
            errs.append(f"ฉาก {i}: image_prompt มีตำแหน่งมุมขวาล่าง ห้ามวางตัวละครหรือจุดสำคัญที่มุมนั้น (เป็นที่ของปุ่มแพลตฟอร์ม)")
        prev = pl
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
        # v4.4: has_living ต่อฉาก (AI ระบุเอง) ถ้าไม่มี/อ่านไม่ได้ ใช้การมี IDENTITY LOCK เป็นตัวสำรอง ไม่ปฏิเสธทั้งบท
        has_living = coerce_bool(s.get("has_living"))
        if has_living is None:
            has_living = bool(extract_identities(img))
            print(f"WARNING: ฉาก {i}: has_living หายไปหรือไม่ถูกต้อง -> ใช้ผลจาก IDENTITY LOCK ({has_living})")
        char_errs = check_scene_characters(i, s, img)
        errs.extend(char_errs)
        if s["characters"]:
            has_living = True  # v4.7: ฉากที่มีตัวละครประจำเป็นฉากมีชีวิตเสมอ
        s["has_living"] = has_living
        errs.extend(check_scene_faces(i, s, has_living))
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
    errs.extend(check_identities(scenes))
    errs.extend(check_hook(scenes))
    errs.extend(check_placements(scenes))
    if CHARACTERS_ENABLED:
        with_chars = sum(1 for s in scenes if isinstance(s, dict) and s.get("characters"))
        if with_chars < 2 or len(scenes) - with_chars < 2:
            errs.append(f"มีตัวละครใน {with_chars}/{len(scenes)} ฉาก ต้องมีอย่างน้อย 2 ฉากที่มีตัวละครและอย่างน้อย 2 ฉากที่ไม่มี (เป้าราวครึ่งหนึ่ง)")
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
        hook_max=HOOK_MAX_CHARS,
        max_c=MAX_CHARS,
        min_s=MIN_SCENES,
        max_s=MAX_SCENES,
        category=todays_category(),
        image_rules=image_rules(),
        kw_rule=keyword_prompt_parts()[0],
        kw_field=keyword_prompt_parts()[1],
        char_rule=character_prompt_parts()[0],
        char_field=character_prompt_parts()[1],
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
