import os
import re

"""Style and scene prompt builder for storybook watercolor illustrations.

v4.7: ตัวละครประจำคลิป 2 ตัว (OZONE เด็กชายนักสำรวจ + ORBI หุ่นยนต์ลอยตัวคู่ใจ)
  - รูปลักษณ์มาจาก "ภาพอ้างอิง" (assets/characters/*.png ส่งเข้า FLUX.2 klein ผ่าน input_image_N) + ข้อความอธิบายสั้นๆ ใน CHARACTERS
    AI เขียนบทไม่ต้องบรรยายหน้าตา/ชุดของตัวละคร เขียนเฉพาะท่าทาง สีหน้า และตำแหน่งตามเนื้อหา (ระบบใส่รูปลักษณ์ให้เอง)
  - ฟิลด์ characters ต่อฉาก = ["ozone","robot"] (ว่าง = ไม่มีตัวละคร ไม่ส่งภาพอ้างอิง) ฉากที่มีตัวละครถือเป็น has_living = true เสมอ
  - ลำดับภาพอ้างอิงที่ส่ง = ลำดับใน CHARACTERS (ozone ก่อน robot) และประโยคใน prompt อ้างว่า "first/second attached image"
    ตามภาพที่ส่งจริงของฉากนั้น (ไม่ผูกกับเลข 0/1 ของ input_image_N)
  - ปิดทั้งระบบด้วย CHARACTERS_ENABLED=0

v4.4: ใช้สไตล์ฐานชุดเดียวทุกฉาก (สีน้ำนิทาน โทนพาสเทล รูปทรงกลมมน เรียบง่าย แสงนุ่ม) ฉากทุกฉากจึงดูเป็นภาพชุดเดียวกัน
  - สิ่งมีชีวิต = kawaii chibi (มีหน้าตา) ตามเดิม
  - สิ่งไม่มีชีวิต = น่ารักจาก "รูปทรงและสี" (ทรงกลมมนนุ่มคล้ายตุ๊กตา พาสเทล ประกายแสงเล็กๆ) ไม่เอ่ยถึงตา/ปาก/แก้ม/แขนขาเลย
    (FLUX.2 klein ไม่มี negative prompt การสั่งห้ามหน้าตากลับดึงหน้าตาเข้ามา)
  - ประเภทฉากมาจากฟิลด์ has_living ที่ AI ระบุต่อฉาก; ถ้าไม่มี/ไม่ถูกต้องใช้ IDENTITY LOCK เป็นตัวสำรอง
  - ฉากที่มีทั้งสองอย่าง: เฉพาะตัวละครมีหน้าตา วัตถุรอบข้างเป็นรูปทรงกลมมนเรียบๆ
  - มุมกล้องแยก 2 ชุด (SHOTS_LIVING / SHOTS_NONLIVING) ชุดไม่มีชีวิตไม่มีคำว่า "characters"

v4.3: แยกสไตล์ตามฉาก (style_for) ฉากไม่มีสิ่งมีชีวิตไม่มีคำว่า eyes/kawaii เลย แก้ปัญหาสมองมีลูกตา

v4.2: น่ารัก (kawaii chibi) เฉพาะ "สิ่งมีชีวิต" เท่านั้น; วัตถุ สถานที่ ปรากฏการณ์ เซลล์ อวัยวะ และองค์ประกอบรอบข้างทั้งหมดสมจริง
ตรงข้อเท็จจริง ไม่มีหน้าตา; build_prompt ตัดคำชวนให้น่ารัก (kawaii/chibi/cute/whimsical ฯลฯ) ออกจากคำบรรยายฉาก
เพราะความน่ารักถูกควบคุมจาก STYLE ส่วนสิ่งมีชีวิตเท่านั้น

v4.0: สไตล์ kawaii chibi ตามภาพตัวอย่าง + สั่งภาพเต็มขอบ (full-bleed, no border/frame/margin) เฉพาะใน prompt
(ไม่มีขั้น crop) ตัดคำว่า "cream paper may show / paper margin" ที่เคยชวนให้โมเดลวาดขอบกระดาษออก

v3.8 (phase A): IMAGE_DETAIL_LEVEL = "rich" (default) or "standard" controls how much storybook detail
the style asks for, and how detailed the script writer's image_prompt must be (see 1_generate_script.py).
"""

_STYLE_BASE = (
    "Storybook watercolor illustration, soft pastel palette, rounded simple shapes, "
    "full-bleed edge-to-edge canvas, delicate dark-brown ink outlines, translucent washes, fine paper grain. "
)
# ฉากที่มีสิ่งมีชีวิต: ตัวละครเป็น kawaii chibi; วัตถุรอบข้างเป็นรูปทรงกลมมนเรียบๆ (ไม่พูดถึงหน้าตาของวัตถุ)
_STYLE_LIVING = (
    "Living characters are kawaii chibi: big head, big glossy black eyes, rosy cheeks, chubby round body, short limbs, pastel tones. "
    "Surrounding objects are smooth soft rounded forms in pastel colors. "
)
# ฉากไม่มีสิ่งมีชีวิต: ความน่ารักมาจากรูปทรงและสีเท่านั้น ห้ามมีคำเกี่ยวกับหน้าตา/แขนขา/kawaii ในข้อความนี้
_STYLE_NONLIVING = (
    "Everything is drawn as soft rounded plush-like shapes in gentle pastel colors with tiny sparkles of light, "
    "clean and simple. "
)
_DEPTH = {
    "rich": "Layered depth, one clear focal point. ",
    "standard": "One clear focal point, setting fills the canvas. ",
}
_STYLE_TAIL = "Soft light. "


def resolve_detail_level() -> str:
    raw = os.getenv("IMAGE_DETAIL_LEVEL", "rich").strip().lower() or "rich"
    if raw not in _DEPTH:
        print(f"WARNING: IMAGE_DETAIL_LEVEL '{raw}' ไม่ถูกต้อง (ใช้ได้: standard, rich) -> ใช้ rich")
        return "rich"
    return raw


IMAGE_DETAIL_LEVEL = resolve_detail_level()


def style_for(has_living: bool) -> str:
    """สไตล์ฐานชุดเดียว + ส่วนเฉพาะประเภทฉาก (มีชีวิต / ไม่มีชีวิต)"""
    return _STYLE_BASE + (_STYLE_LIVING if has_living else _STYLE_NONLIVING) + _DEPTH[IMAGE_DETAIL_LEVEL] + _STYLE_TAIL


STYLE = style_for(False)  # เก็บไว้เพื่อความเข้ากันได้กับโค้ดที่ import STYLE

# Shot variety is a suggestion; scenes starting with cross-section/macro skip it (see build_prompt).
# v4.4: แยกเป็น 2 ชุด ชุดไม่มีสิ่งมีชีวิตไม่มีคำว่า "characters" และ "eye" (กันโมเดลวาดตัวละคร/ตาในฉากวัตถุ)
SHOTS_LIVING = [
    "Use a medium shot that shows the characters' poses together with their surroundings.",
    "Use a wide establishing composition with clear foreground, middle ground and background.",
    "Use a low-angle viewpoint when appropriate.",
    "Use a bird's-eye viewpoint when appropriate.",
    "Use a side/profile viewpoint when appropriate.",
    "Use a detailed close-up when the subject benefits from it.",
    "Use an over-the-shoulder or three-quarter viewpoint when appropriate.",
    "Use a balanced environmental composition with layered depth.",
]
SHOTS_NONLIVING = [
    "Use a medium shot that shows the main subject together with its surroundings.",
    "Use a wide establishing composition with clear foreground, middle ground and background.",
    "Use a low-angle viewpoint when appropriate.",
    "Use a high top-down overhead viewpoint when appropriate.",  # ไม่ใช้คำว่า bird's-eye (มีคำว่า eye)
    "Use a side/profile viewpoint when appropriate.",
    "Use a detailed close-up when the subject benefits from it.",
    "Use a three-quarter viewpoint when appropriate.",
    "Use a balanced environmental composition with layered depth.",
]
SHOTS = SHOTS_LIVING  # เก็บไว้เพื่อความเข้ากันได้กับโค้ดที่ import SHOTS

# IDENTITY LOCK: รูปแบบที่บังคับ = บรรทัดแยก  IDENTITY LOCK: [คำอธิบายภาษาอังกฤษ]
IDENTITY_BRACKET_RE = re.compile(r"IDENTITY\s+LOCK\s*:\s*\[([^\]\n]+)\]", re.I)
# สำรอง (กรณี AI ลืมวงเล็บ): จับเฉพาะถึงท้ายบรรทัดเดียวกัน ไม่ข้ามบรรทัด
IDENTITY_LINE_RE = re.compile(r"IDENTITY\s+LOCK\s*:[ \t]*([^\n\[\]]+)", re.I)


def extract_identities(image_prompt: str) -> list[str]:
    """คืนรายการข้อความ identity ใน image_prompt (ว่าง = ไม่มี IDENTITY LOCK ที่อ่านได้)"""
    text = str(image_prompt)
    found = [m.strip() for m in IDENTITY_BRACKET_RE.findall(text)]
    if not found:
        found = [m.strip().rstrip(".") for m in IDENTITY_LINE_RE.findall(text)]
    return [f for f in found if f]


def strip_identity(image_prompt: str) -> str:
    """ตัดส่วน IDENTITY LOCK ออกจากคำอธิบายฉาก (จะใส่กลับเป็นประโยคคำสั่งแยกต่างหาก)"""
    text = IDENTITY_BRACKET_RE.sub(" ", str(image_prompt))
    text = IDENTITY_LINE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


# v4.4: คำเกี่ยวกับหน้าตา/แขนขา ที่ห้ามปรากฏในฉากไม่มีสิ่งมีชีวิต (ตรวจใน 1_generate_script.py)
FACE_WORDS_RE = re.compile(
    r"\b(?:eyes?|eyelashes|cheeks?|mouths?|smil\w*|grin\w*|lips|arms?|legs?|face|faces|facial|kawaii|chibi|cute|adorable)\b",
    re.I,
)
# วลีที่เป็นคำศัพท์จริงของวัตถุ/ภูมิประเทศ/กายวิภาค ไม่ใช่หน้าตา -> ตัดออกก่อนตรวจ (heuristic)
FACE_SAFE_RE = re.compile(
    r"\b(?:"
    r"spiral arms?|galactic arms?|arms? of (?:the |a )?(?:galaxy|sea|river|crane|lever)|"
    r"(?:rock|cliff|north|south|east|west|mountain|clock|watch|coin)\s+faces?|faces? of (?:the |a )?(?:cliff|mountain|rock|clock|moon|coin|crystal|cube|dice)|"
    r"(?:river|cave|tunnel|volcano)\s+mouths?|mouths? of (?:the |a )?(?:river|cave|tunnel|volcano)|"
    r"eyes? of (?:the |a )?(?:storm|hurricane|needle|cyclone)|(?:table|chair|tripod|piano)\s+legs?|"
    r"(?:human|anatomical|muscle|bone|skeletal|upper|lower)\s+(?:arms?|legs?|face|mouth|eyes?)|"
    r"(?:arms?|legs?|face|mouth|eyes?)\s+(?:muscles?|bones?|nerves?|tissues?|sockets?|cavity|skin)"
    r")\b",
    re.I,
)


def has_face_words(text: str) -> bool:
    """True ถ้าข้อความมีคำเกี่ยวกับหน้าตา/แขนขา/kawaii (หลังตัดวลีศัพท์จริงที่ปลอดภัยออก)"""
    return bool(FACE_WORDS_RE.search(FACE_SAFE_RE.sub(" ", str(text))))


def coerce_bool(value):
    """แปลงค่าฟิลด์ has_living เป็น True/False; คืน None ถ้าไม่มี/อ่านไม่ได้ (ให้ผู้เรียกใช้ตัวสำรอง)"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "y", "1"):
            return True
        if v in ("false", "no", "n", "0"):
            return False
    return None


def scene_has_living(scene: dict) -> bool:
    """ประเภทฉาก: ใช้ has_living ที่ AI ระบุ ถ้าไม่มี/ไม่ถูกต้องใช้การมี IDENTITY LOCK เป็นตัวสำรอง"""
    if scene_characters(scene):
        return True  # v4.7: ฉากที่มีตัวละครประจำถือเป็นฉากมีชีวิตเสมอ
    flag = coerce_bool(scene.get("has_living"))
    if flag is not None:
        return flag
    return bool(extract_identities(scene.get("image_prompt", "")))


# ---------------------------------------------------------------------------
# v4.7: ตัวละครประจำคลิป
# ---------------------------------------------------------------------------
CHARACTERS_ENABLED = os.getenv("CHARACTERS_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")

# ลำดับในดิกต์นี้ = ลำดับภาพอ้างอิงที่ส่งให้โมเดล (ozone ก่อน robot)
# name = ชื่อที่ AI ต้องเรียกใน image_prompt (ORBI เป็นชื่อชั่วคราว เปลี่ยนได้ที่นี่ที่เดียว)
# desc = คำอธิบายสั้นๆ ช่วยโมเดลจับตัวตน (ภาพอ้างอิงเป็นตัวบอกรูปลักษณ์หลัก จึงไม่ต้องยาว)
CHARACTERS = {
    "ozone": {
        "name": "OZONE",
        "ref": "assets/characters/ozone.png",
        "desc": "a chibi boy with silver-white hair fading to mint green and a white and green space jacket",
    },
    "robot": {
        "name": "ORBI",
        "ref": "assets/characters/robot.png",
        "desc": "a small round white floating robot with a black screen face and green glowing details",
    },
}


def raw_character_items(value) -> list[str]:
    """แปลงค่าฟิลด์ characters (ลิสต์หรือสตริงคั่นจุลภาค) เป็นลิสต์ข้อความตัวพิมพ์เล็ก (ยังไม่กรองรหัสที่ไม่รู้จัก)"""
    if value is None:
        return []
    if isinstance(value, str):
        value = [v for v in re.split(r"[,\s]+", value) if v]
    if not isinstance(value, (list, tuple)):
        return [str(value).strip().lower()]
    return [str(v).strip().lower() for v in value if str(v).strip()]


def normalize_characters(value) -> list[str]:
    """รหัสตัวละครที่ถูกต้อง เรียงตาม CHARACTERS ไม่ซ้ำ; ปิดระบบ = ลิสต์ว่าง"""
    if not CHARACTERS_ENABLED:
        return []
    items = set(raw_character_items(value))
    return [cid for cid in CHARACTERS if cid in items]


def scene_characters(scene: dict) -> list[str]:
    return normalize_characters(scene.get("characters"))


# v4.8: ตำแหน่งตัวละครต่อฉาก (ให้ FLUX วาดเอง แก้ที่พรอมต์) ห้ามมุมขวาล่างเพราะเป็นที่ของปุ่มแพลตฟอร์ม
# ขอบล่างเว้นไว้สำหรับซับไตเติล ตำแหน่งขอบอนุญาตให้ตัวละครโผล่ครึ่งตัว/ถูกเฟรมตัดได้ แต่ต้องเห็นจุดเด่นของตัวละคร
PLACEMENTS = {
    "hero_center": "Hero framing: the characters are large, close to the camera and centered, faces clearly visible",
    "left_edge": "Place the characters at the left edge of the frame in the upper or middle area, partly cropped by the frame edge when natural",
    "right_edge": "Place the characters at the right edge of the frame in the upper or middle area, partly cropped by the frame edge when natural",
    "top_peek": "The characters peek in from the top edge, upper half visible and cropped by the frame, with faces visible",
    "bottom_left": "Place the characters small in the lower-left, above the bottom quarter, partly tucked behind a scene element when natural",
}
PLACEMENT_ORDER = list(PLACEMENTS)  # hero_center ใช้เฉพาะฉากฮุก (ฉากที่ 1)
NEVER_ZONE = "never in the bottom-right corner, keep the bottom quarter uncluttered"
# คำที่ห้ามอยู่ใน image_prompt ของฉากที่มีตัวละคร (มุมขวาล่าง)
BOTTOM_RIGHT_RE = re.compile(
    r"\b(?:bottom|lower)[\s-]*right\b|\bright[\s-]*(?:bottom|lower)\b|\bbottom[\s-]*right[\s-]*corner\b", re.I)


def normalize_placement(value, scene_id: int = 1) -> str:
    """รหัสตำแหน่งที่ถูกต้อง; ไม่ถูกต้อง/ไม่มี -> ค่าสำรองตามเลขฉาก (ฉาก 1 = hero_center, ฉากอื่นหมุนเวียนตำแหน่งขอบ)"""
    v = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if v in PLACEMENTS and (v != "hero_center" or int(scene_id) == 1):
        return v
    if int(scene_id) == 1:
        return "hero_center"
    edge = PLACEMENT_ORDER[1:]
    return edge[(int(scene_id) - 2) % len(edge)]


def character_instruction(ids: list[str], placement: str = "hero_center") -> str:
    """ประโยคกำกับให้โมเดลใช้ตัวละครจากภาพอ้างอิงที่แนบ (เรียงตาม ids ตรงกับลำดับภาพที่ส่งจริง)"""
    if not ids:
        return ""
    ordinals = ["first", "second", "third", "fourth"]
    parts = [
        f"the {ordinals[i]} attached reference image shows {CHARACTERS[cid]['name']}, {CHARACTERS[cid]['desc']}"
        for i, cid in enumerate(ids)
    ]
    place = PLACEMENTS.get(placement, PLACEMENTS["hero_center"])
    return (
        "Draw the recurring characters exactly as in the attached reference images (same design, colors, outfit): "
        + "; ".join(parts)
        + ". Ignore the reference backgrounds. Pose and expression follow the scene. "
        + place + ", " + NEVER_ZONE + "."
    )


# v4.2: คำที่ทำให้โมเดลภาพเติมความน่ารัก/หน้าตาให้ของทุกอย่าง -> ตัดออกจากคำบรรยายฉากและ IDENTITY LOCK
# (ความน่ารักของสิ่งมีชีวิตมาจาก STYLE ส่วน _STYLE_LIVING อยู่แล้ว)
MAX_PROMPT_CHARS = int(os.getenv("IMAGE_PROMPT_MAX_CHARS", "2000"))
CUTE_WORDS_RE = re.compile(
    r"\b(?:kawaii|chibi|cute|cutest|adorable|whimsical(?:ly)?|charming(?:ly)?|delightful(?:ly)?|playful(?:ly)?|friendly|anthropomorphic|personified)\b[,]?\s*",
    re.I,
)


def strip_cute_words(text: str) -> str:
    cleaned = CUTE_WORDS_RE.sub("", str(text))
    cleaned = re.sub(r"\bin\s+(?:a\s+)?(?:pastel\s+)?(?:style\s+)?watercolor\.?$", "", cleaned.strip(), flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip()


def build_prompt(scene: dict) -> str:
    raw_desc = str(scene.get("image_prompt", "")).strip()
    has_living = scene_has_living(scene)
    identities = [strip_cute_words(i) for i in extract_identities(raw_desc)]
    identities = [i for i in identities if i]
    scene_desc = strip_identity(raw_desc).rstrip(".") if identities else re.sub(r"\s+", " ", raw_desc).rstrip(".")
    # ภาพตัดขวาง/ภาพขยายใกล้กำหนดมุมกล้องเองอยู่แล้ว -> ไม่ใส่ shot ซ้ำให้ชนกัน
    scene_desc = strip_cute_words(scene_desc)
    if re.match(r"(cross-section|close-up macro)", scene_desc, re.I):
        shot = ""
    else:
        shots = SHOTS_LIVING if has_living else SHOTS_NONLIVING
        shot = shots[max(0, int(scene.get("id", 1)) - 1) % len(shots)]
    identity_instruction = ""
    if identities:
        if has_living:
            identity_instruction = (
                "CHARACTER / SUBJECT IDENTITY MUST MATCH EXACTLY: "
                + "; ".join(identities)
                + ". Preserve the same species, anatomy, proportions, base colors, "
                  "markings, and distinctive features. Only pose, action, expression, "
                  "camera angle, and environment may change as the scene requires."
            )
        else:
            # ฉากไม่มีสิ่งมีชีวิต: ไม่ใช้คำว่า anatomy/expression/character ที่ชวนให้เติมหน้าตา
            identity_instruction = (
                "SUBJECT MUST MATCH EXACTLY: "
                + "; ".join(identities)
                + ". Preserve the same shape, proportions, base colors, "
                  "markings, and distinctive features. Only position, "
                  "camera angle, and environment may change as the scene requires."
            )
    char_ids = scene_characters(scene)
    char_instruction = character_instruction(char_ids, normalize_placement(scene.get("placement"), scene.get("id", 1)))
    # v3.6: ไม่ส่งบทพากย์ (narration) เข้าโมเดลภาพ เพราะ T1 พบว่าโมเดลเอาบทมาเขียนเป็นตัวหนังสือในภาพ
    # image_prompt บรรยายฉากครบในตัวอยู่แล้ว
    # ลำดับ: ฉาก -> identity -> มุมกล้อง -> สไตล์ (FLUX ให้น้ำหนักข้อความช่วงต้น)
    parts = [style_for(has_living), f"Scene: {scene_desc}.", char_instruction, identity_instruction, shot]
    prompt = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()
    # เพดานความยาว prompt ภาพ (FLUX บน Cloudflare รับได้ราว 2048 ตัวอักษร) -> ตัดมุมกล้อง (ไม่บังคับ) ก่อน
    if len(prompt) > MAX_PROMPT_CHARS and shot:
        prompt = re.sub(r"\s+", " ", " ".join(p for p in parts[:-1] if p)).strip()  # ตัดเฉพาะมุมกล้อง (ตัวสุดท้าย)
    if len(prompt) > MAX_PROMPT_CHARS:
        print(f"WARNING: image prompt ฉาก {scene.get('id')} ยาว {len(prompt)} ตัวอักษร เกิน {MAX_PROMPT_CHARS} ผู้ให้บริการภาพอาจตัดท้ายข้อความ")
    return prompt
