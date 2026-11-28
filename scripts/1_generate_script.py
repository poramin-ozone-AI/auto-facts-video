"""ขั้น 1: สร้างบทความรู้แปลกๆ + แบ่งฉาก -> output/script.json

ผู้ให้บริการ: Gemini (หลัก, ลองหลายรุ่นตามลำดับ) -> Groq (สำรอง) ทั้งคู่มี free tier
Secrets: GEMINI_API_KEY (จำเป็น), GROQ_API_KEY (แนะนำเป็นตัวสำรอง)
ตัวแปร env ที่ปรับได้:
  - GEMINI_MODEL            (ค่าเริ่มต้น: gemini-3.8-flash)
  - GEMINI_FALLBACK_MODELS  (ค่าเริ่มต้น: gemini-3.6-flash,gemini-3.5-flash-lite  คั่นด้วยจุลภาค)
  - GROQ_MODEL              (ค่าเริ่มต้น: openai/gpt-oss-120b)
  - CHARACTERS_ENABLED      (ค่าเริ่มต้น: 1; v4.7) เปิด/ปิดตัวละครประจำคลิป OZONE + ORBI (ปิด = ไม่ขอฟิลด์ characters และไม่ส่งภาพอ้างอิง)
  - จำนวนฉาก: ให้ AI เลือกตามเนื้อหาและจังหวะการเล่า ไม่มีช่วงจำนวนฉากตายตัว
  - HOOK_MAX_CHARS        (ค่าเริ่มต้น: 60; v4.8) ความยาวสูงสุดของคำถามฮุกในฉากที่ 1 (ราว 4-5 วินาที)
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

# ความยาวบทพากย์ไม่มีเกณฑ์ตัวอักษรตายตัว; ควบคุมระยะเวลาจริงหลังสร้างเสียงในขั้น 2
HOOK_MAX_CHARS = int(os.getenv("HOOK_MAX_CHARS", "60"))  # v4.8: ความยาวสูงสุดของคำถามฮุก (ฉากที่ 1) ราว 4-5 วินาที
# เพดานโทเคนคำตอบ (v3.8: image_prompt ยาวขึ้น) Gemini นับโทเคนที่ "คิด" รวมด้วย จึงตั้งสูงไว้ก่อน
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "16384"))
# Groq ฟรีจำกัดโทเคน/นาทีต่ำ (~8K รวม prompt) จึงไม่ยกเพดานเกิน 6000 โดยอัตโนมัติ
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "6000"))

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
    """คืนกฎตัวละครและฟิลด์ JSON; ปิด CHARACTERS_ENABLED แล้วไม่ส่งทั้งคู่"""
    if not CHARACTERS_ENABLED:
        return "", ""
    o, r = CHARACTERS["ozone"]["name"], CHARACTERS["robot"]["name"]
    rule = (
        f"- ตัวละครประจำคลิป: {o} (เด็กชายนักสำรวจชุดอวกาศ) และ {r} (หุ่นยนต์ลอยตัวกลม) "
        "ระบบแนบภาพอ้างอิงและกำหนดรูปลักษณ์ให้เอง ทุกฉากต้องมี characters เป็นลิสต์ของ ozone/robot หรือ []\n"
        "- ใช้เฉพาะเมื่อช่วยอธิบาย เพิ่มความเป็นมิตร หรือเชื่อมการเล่า ไม่กำหนดสัดส่วนและไม่จำเป็นต้องปรากฏทุกคลิป "
        "ฉากที่ต้องเน้นข้อเท็จจริงโดยตรง เช่น ภาพตัดขวาง ภาพขยาย จำนวน ขนาด หรือสัดส่วน ให้ใช้ [] ได้\n"
        f"- เมื่อใช้ ให้เรียก {o}/{r} ด้วยชื่อตรงตัวใน image_prompt และระบุท่าทาง การกระทำ สีหน้า และตำแหน่งให้สัมพันธ์กับ narration; "
        "ห้ามเพิ่มข้อเท็จจริง วัตถุ หรือเหตุการณ์ที่บทไม่ได้กล่าวถึง ระบบกำหนดหน้าตา ชุด และสีจากภาพอ้างอิง จึงไม่ต้องบรรยายหรือใส่ IDENTITY LOCK ให้สองตัวนี้\n"
        f"- เรียกหุ่นยนต์ว่า {r} เท่านั้น (ห้ามใช้คำว่า robot); สีหน้าเขียนเป็น \"{r}'s screen shows ...\" "
        f"เช่น happy closed-arc eyes หรือ worried eyes และให้ {r} ลอยอยู่กลางอากาศ\n"
        "- narration เป็นเสียงผู้บรรยายคนเดียว ตัวละครไม่มีบทพูด\n"
        "- ทุกฉากที่มีตัวละครต้องเลือก placement หนึ่งค่า: hero_center (ใช้ได้เฉพาะฉาก 1), left_edge, top_peek หรือ bottom_left; "
        "ห้ามใช้ตำแหน่งเดียวกับฉากก่อนหน้าที่มีตัวละคร และห้ามบังจุดโฟกัส หากวางชิดขอบให้บอกตำแหน่งและการถูกเฟรมตัดใน image_prompt "
        "เว้นขอบล่างและมุมขวาล่างสำหรับซับและปุ่มแพลตฟอร์ม"
    )
    return rule + "\n", ' "characters": ["ozone", "robot"], "placement": "hero_center",'


def image_rules() -> str:
    """กฎ image_prompt ตาม IMAGE_DETAIL_LEVEL"""
    common = (
        "- เขียน image_prompt เป็นภาษาอังกฤษ ความยาวยืดหยุ่นตามความซับซ้อนของภาพ ไม่ต้องนับหรือบังคับจำนวนคำ "
        "ใช้คำบรรยายเชิงบวกเท่านั้น เพราะโมเดลภาพไม่มี negative prompt และคำปฏิเสธอาจทำให้วาดสิ่งที่ห้าม\n"
        "- เริ่มด้วยประโยคที่ระบุ subject, action และ setting ให้ชัด แล้วเรียงรายละเอียดจากสิ่งสำคัญไปสู่รายละเอียดรอง\n"
        "- วาดสิ่งที่ narration กล่าวถึงให้ตรงทั้งการกระทำ จำนวน ขนาด สัดส่วน สี และตำแหน่ง; หากกล่าวถึงการกระทำของคน/สัตว์ ต้องเห็นกำลังทำจริง "
        "สื่อจำนวนและสัดส่วนด้วยองค์ประกอบภาพ ไม่ใช้ตัวเลขเขียนบนภาพ\n"
        "- เพิ่มเฉพาะรายละเอียดจริงที่ช่วยอธิบายเรื่อง หากไม่แน่ใจทางกายวิภาคหรือประวัติศาสตร์ ให้เลือกภาพเรียบง่ายที่ถูกต้อง\n"
        "- สิ่งที่มองไม่เห็นจากภายนอก (ใต้ดิน ในร่างกาย จุลชีพ ใต้ทะเลลึก หรือในอะตอม) ให้เริ่มด้วย cross-section cutaway view หรือ close-up macro view "
        "แล้วจึงใส่ IDENTITY LOCK หากจำเป็น\n"
    )
    if IMAGE_DETAIL_LEVEL == "rich":
        detail = (
            "- สร้างภาพที่มีมิติและรายละเอียดเท่าที่ช่วยเล่าเรื่อง อาจใช้ foreground, middle ground, background, "
            "แสง หรือองค์ประกอบแวดล้อมเมื่อเหมาะกับฉาก แต่ไม่จำเป็นต้องมีครบทุกชั้นหรือมีของประกอบตามจำนวนที่กำหนด\n"
            "- ทุกองค์ประกอบเสริมต้องเกี่ยวข้องและไม่ขัดกับข้อเท็จจริง หากรายละเอียดตกแต่งทำให้ภาพคลาดเคลื่อน ให้ตัดออก\n"
            "- หากมีหลายองค์ประกอบสำคัญ ให้แบ่งตามจังหวะการเล่า ไม่ยัดทุกอย่างไว้ในฉากเดียว\n"
            "- ตัวอย่างรูปแบบเป็นเพียงแนวทางเรื่องการจัดองค์ประกอบ ไม่ใช่ข้อบังคับให้ทุกภาพต้องมีหลายชั้น\n"
        )
    else:
        detail = "- ใช้องค์ประกอบเท่าที่จำเป็น ให้จุดโฟกัสหลักชัดเจน; เพิ่มฉากหลังหรือรายละเอียดประกอบเมื่อช่วยให้เข้าใจเรื่อง\n"
    tail = (
        "\n- เมื่อสิ่งเดิมปรากฏหลายฉาก ให้ใส่ IDENTITY LOCK เป็นบรรทัดแยกท้าย image_prompt รูปแบบ `IDENTITY LOCK: [คำอธิบายภาษาอังกฤษ]` "
        "ระบุชนิดหรือชื่อเฉพาะให้ชัด ตามด้วยสี ลวดลาย สัดส่วน และจุดเด่น แล้วคัดลอกข้อความเดิมทุกฉาก; เปลี่ยนได้เฉพาะท่าทาง กิจกรรม มุมกล้อง และสภาพแวดล้อม "
        "สิ่งใหม่ใช้ lock ใหม่ ฉากที่ไม่มีสิ่งนั้นไม่ต้องใส่ แต่ละฉากต้องบรรยายครบในตัวเอง\n"
        "- IDENTITY LOCK ของกลุ่มคน/สัตว์ใช้ได้; ของสิ่งไม่มีชีวิตให้บรรยายเฉพาะรูปทรง สี วัสดุ และลวดลาย\n"
        "- ห้ามมีตัวหนังสือ ตัวเลข เครื่องหมายคำพูด หรือบอลลูนคำพูดในภาพ; ป้าย ใบเรือ โล่ และผนังเป็นพื้นผิวเปล่า"
    )
    return common + detail + tail


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


PROMPT = """คุณเป็นนักเขียนบทคลิปสั้นภาษาไทยแนว "ความรู้แปลกๆ ที่คนส่วนใหญ่ไม่รู้" สร้างเรื่องที่น่าสนใจ เข้าใจง่าย และน่าเชื่อถือ

หัวข้อที่ใช้แล้ว (ห้ามซ้ำหรือใกล้เคียง):
{history}
หมวดวันนี้ (เลือกหัวข้อใหม่ในหมวดนี้): {category}

หลักความถูกต้อง:
- เลือกข้อเท็จจริงที่ตรวจสอบได้จากวิทยาศาสตร์ ประวัติศาสตร์ ธรรมชาติ หรือจิตวิทยา; หากไม่มั่นใจให้เลือกเรื่องอื่น
- ห้ามแต่งตัวเลข สถิติ วันที่ ชื่อบุคคล กลไก หรือคำพูดอ้างอิง; ระบุความไม่แน่นอนเมื่อข้อมูลเป็นค่าประมาณหรือยังถกเถียงกัน และใช้คำเด็ดขาด เช่น ทุก/เสมอ/ไม่มีทาง เฉพาะเมื่อไม่มีข้อยกเว้น
- source_hint เป็นรายการแหล่งข้อมูลที่ผู้ใช้ใช้ตรวจสอบต่อได้ เลือกเฉพาะหน่วยงาน/สถาบัน/เอกสารที่เกี่ยวข้องโดยตรงกับข้อเท็จจริงหลักของเรื่อง ไม่ใส่ชื่อเพื่อให้ครบจำนวน และห้ามแต่งชื่อรายงานหรือแหล่งอ้างอิง; ใส่เท่าที่ระบุได้อย่างมั่นใจ หากไม่มั่นใจให้ใช้ [] ไม่ต้องใส่ URL

ข้อมูลโพสต์:
- title คือชื่อคลิป
- description คือคำอธิบายใต้คลิป 1-2 ประโยค ชวนติดตามโดยไม่เฉลยทั้งหมด
- hashtags คือแฮชแท็กที่เกี่ยวข้อง 3-5 รายการ แต่ละรายการขึ้นต้นด้วย # และไม่มีช่องว่าง

โครงเรื่อง:
- ฉาก 1 เป็น HOOK: เปิดด้วยคำถามเฉพาะเจาะจง ไม่เกิน {hook_max} ตัวอักษร ลงท้ายด้วย ? หรือคำถามภาษาไทย (ไหม/ทำไม/อะไร/กี่); ต้องตอบได้จริงจากเนื้อหาถัดไปและห้ามแฝงข้อมูลผิด ฉากนี้ไม่ต้องเพิ่มข้อเท็จจริงใหม่
- ฉาก 2 เริ่มตอบ HOOK ทันที จากนั้นอธิบายตามลำดับเหตุผล ทุกฉากหลังจากนั้นต้องเพิ่มข้อเท็จจริง มุมอธิบาย ตัวอย่าง หรือผลลัพธ์ที่จำเป็น เชื่อมโยงกันและไม่พูดซ้ำ; รวมฉากที่ซ้ำหรือตัดออก
- หนึ่งฉากควรสื่อสารหนึ่งประเด็นหรือภาพจำหลัก ไม่จำเป็นต้องเปลี่ยนฉากทุกครั้งที่เปลี่ยนประโยค; แยกฉากเมื่อเปลี่ยนสถานที่ ช่วงเวลา กลไก หรือภาพที่จำเป็นต่อความเข้าใจ
- ฉากสุดท้ายคลี่คลายประเด็นที่เปิดไว้และจบด้วยข้อคิดหรือภาพจำสั้นๆ ที่เกี่ยวข้อง

บทพากย์:
- ไม่มีจำนวนตัวอักษรขั้นต่ำหรือสูงสุดตายตัว ให้ความยาวและจำนวนฉากขึ้นอยู่กับความซับซ้อนและเนื้อหาที่จำเป็น
- เล่าให้ครบประเด็นโดยไม่ยืดด้วยคำซ้ำ ตัวอย่างที่ไม่จำเป็น หรือคำเกริ่นยาว และไม่ตัดข้อเท็จจริงสำคัญเพียงเพื่อให้สั้น
- เป้าหมายคือคลิปสั้น: เขียนให้กระชับและอยู่ในช่วงเวลาที่ระบบกำหนดเมื่อสร้างเสียงจริง หากเนื้อหามีสาระจำเป็นมากกว่าปกติให้เล่าตามความจำเป็น ไม่บีบเนื้อหาให้ได้จำนวนตัวอักษร
- ใช้ภาษาไทยพูดจริง เป็นมิตร น่าเชื่อถือ ประโยคกระชับและอ่านออกเสียงลื่น
- เขียนตัวเลขทศนิยม หน่วย และตัวย่อวิทยาศาสตร์ใน narration เป็นคำอ่านภาษาไทย เช่น 37.2 = “สามสิบเจ็ดจุดสอง”, CO₂ = “คาร์บอนไดออกไซด์”; ใน image_prompt ใช้ตัวเลขได้
{kw_rule}
ภาพ:
- ทุกฉากมี image_prompt ภาษาอังกฤษสำหรับภาพแนวตั้ง 9:16 เลือก subject ให้ตรง narration และหลากหลายตามความเหมาะสม; ให้มีจุดโฟกัสหลักหนึ่งจุด
- ระบุ has_living ทุกฉาก: true เมื่อมีคน สัตว์ แมลง หรือสิ่งมีชีวิตขนาดเล็ก; false เมื่อไม่มีสิ่งมีชีวิต (รวมวัตถุ สถานที่ ปรากฏการณ์ ดวงดาว เซลล์ อวัยวะ โมเลกุล และภาพตัดขวาง)
- ฉาก has_living=false: ความน่ารักมาจากรูปทรงและสี เช่น soft rounded plush-like shapes in pastel colors with tiny sparkles; ห้ามใช้คำว่า eyes, face, mouth, cheeks, smile, arms, legs, kawaii, chibi หรือ cute แม้ในประโยคปฏิเสธ เพราะอาจชักนำให้โมเดลวาดสิ่งเหล่านี้
- ฉาก has_living=true: ให้เฉพาะสิ่งมีชีวิตมีหน้าตา; วัตถุรอบข้างเป็นรูปทรงกลมมนเรียบ และรายละเอียดข้อเท็จจริงทางวิทยาศาสตร์/ประวัติศาสตร์ต้องถูกต้อง
- สิ่งเดิมที่ปรากฏหลายฉากต้องคงชนิดและเอกลักษณ์ (รูปร่าง สัดส่วน สี ลวดลาย จุดเด่น) โดยใช้ IDENTITY LOCK ตามกฎด้านล่าง; ห้ามใช้ “same as previous image”
{char_rule}{image_rules}

ตอบเป็น JSON เท่านั้น ห้ามมีข้อความนอก JSON และใช้โครงสร้างนี้:
{{"topic":"หัวข้อสั้นๆ", "title":"ชื่อคลิป", "description":"คำอธิบายใต้คลิป", "hashtags":["#แฮชแท็ก"], "source_hint":[],
  "scenes":[{{"id":1, "narration":"ข้อความพากย์",{kw_field} "has_living":true,{char_field} "image_prompt":"..."}}]}}"""


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


HOOK_QUESTION_RE = re.compile(r"[?？]|ไหม|หรือเปล่า|หรือไม่|อะไร|ทำไม|อย่างไร|ยังไง|เท่าไร|เท่าไหร่|ใคร|ที่ไหน|เมื่อไร|เมื่อไหร่|กี่")  # v4.9: ตัด "หรือ" (ติดเกือบทุกประโยค)
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
    """(v5.0) ตรวจ placement: ค่าถูกต้อง, hero_center ใช้ได้เฉพาะฉากที่ 1,
    ไม่ซ้ำกับฉากก่อนหน้าที่มีตัวละคร, image_prompt ไม่มีมุมขวาล่าง; ตั้ง s["placement"] เป็นค่าที่ถูกต้อง (ไม่มีตัวละคร = "")"""
    if not CHARACTERS_ENABLED:
        return []
    errs, prev = [], None
    for i, s in enumerate(scenes, 1):
        if not isinstance(s, dict):
            continue
        if not s.get("characters"):
            s["placement"] = ""
            continue
        raw = str(s.get("placement") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if raw not in PLACEMENTS:
            errs.append(f"ฉาก {i}: placement '{raw}' ไม่ถูกต้อง ใช้ได้เฉพาะ {list(PLACEMENTS)}")
        elif raw == "hero_center" and i != 1:
            errs.append(f"ฉาก {i}: hero_center ใช้ได้เฉพาะฉากที่ 1 ฉากนี้ให้เลือกตำแหน่งขอบอื่น")
        pl = normalize_placement(raw, i)
        s["placement"] = pl
        if i == 1 and pl != "hero_center":
            errs.append("ฉากที่ 1: เมื่อมีตัวละคร ต้องใช้ placement แบบ hero_center (ใหญ่ เห็นหน้าชัด)")
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
    for k in ("topic", "title"):
        if not d.get(k):
            errs.append(f"ขาดฟิลด์ {k}")
    if "scenes" not in d:
        errs.append("ขาดฟิลด์ scenes")
    if d.get("topic") and norm(d["topic"]) in {norm(t) for t in used_topics}:
        errs.append(f"หัวข้อ '{d['topic']}' ซ้ำกับที่เคยใช้แล้ว")
    scenes = d.get("scenes") or []
    if not isinstance(scenes, list) or not scenes:
        errs.append("scenes ต้องเป็นลิสต์ที่มีอย่างน้อย 1 ฉาก")
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
    return errs


def clean_post_info(d: dict) -> None:
    """(v4.9) description + hashtags สำหรับโพสต์ ไม่ถูกต้อง/ขาด = WARNING และใช้ค่าสำรอง ไม่ปฏิเสธทั้งบท"""
    desc = re.sub(r"\s+", " ", str(d.get("description") or "")).strip()
    if not desc:
        print("WARNING: ไม่มี description จาก AI -> ใช้ชื่อคลิปแทน")
        desc = str(d.get("title", "")).strip()
    raw = d.get("hashtags") or []
    if isinstance(raw, str):
        raw = re.split(r"[\s,]+", raw)
    tags: list[str] = []
    for t in raw if isinstance(raw, list) else []:
        t = "#" + re.sub(r"[\s#]+", "", str(t))
        if len(t) > 1 and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    if not tags:
        print("WARNING: ไม่มี hashtags จาก AI -> ไม่ใส่แฮชแท็ก")
    d["description"], d["hashtags"] = desc, tags[:5]


def write_post_info(d: dict) -> None:
    """(v4.9) output/post_info.txt: ชื่อคลิป + คำอธิบาย + แฮชแท็ก สำหรับคัดลอกไปโพสต์"""
    text = f"{d['title']}\n\n{d['description']}\n\n{' '.join(d['hashtags'])}\n"
    (OUT / "post_info.txt").write_text(text, encoding="utf-8")


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
        hook_max=HOOK_MAX_CHARS,
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
                    clean_post_info(data)
                    write_post_info(data)
                    data["provider"] = name
                    data["model"] = model
                    (OUT / "script.json").write_text(
                        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    total = sum(len(s["narration"].strip()) for s in data["scenes"])
                    print(f"OK ({name}:{model}) หัวข้อ: {data['topic']} | {len(data['scenes'])} ฉาก | {total} ตัวอักษร (ไม่มีเกณฑ์ผ่าน/ไม่ผ่านตามจำนวนตัวอักษร)")
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
