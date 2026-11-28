import os
import re

"""Style and scene prompt builder for storybook watercolor illustrations.

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
    flag = coerce_bool(scene.get("has_living"))
    if flag is not None:
        return flag
    return bool(extract_identities(scene.get("image_prompt", "")))


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
    # v3.6: ไม่ส่งบทพากย์ (narration) เข้าโมเดลภาพ เพราะ T1 พบว่าโมเดลเอาบทมาเขียนเป็นตัวหนังสือในภาพ
    # image_prompt บรรยายฉากครบในตัวอยู่แล้ว
    # ลำดับ: ฉาก -> identity -> มุมกล้อง -> สไตล์ (FLUX ให้น้ำหนักข้อความช่วงต้น)
    parts = [style_for(has_living), f"Scene: {scene_desc}.", identity_instruction, shot]
    prompt = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()
    # เพดานความยาว prompt ภาพ (FLUX บน Cloudflare รับได้ราว 2048 ตัวอักษร) -> ตัดมุมกล้อง (ไม่บังคับ) ก่อน
    if len(prompt) > MAX_PROMPT_CHARS and shot:
        prompt = re.sub(r"\s+", " ", " ".join(p for p in parts[:3] if p)).strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        print(f"WARNING: image prompt ฉาก {scene.get('id')} ยาว {len(prompt)} ตัวอักษร เกิน {MAX_PROMPT_CHARS} ผู้ให้บริการภาพอาจตัดท้ายข้อความ")
    return prompt
