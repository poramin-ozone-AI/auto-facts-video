import os
import re

"""Style and scene prompt builder for varied watercolor illustrations.

Cream watercolor paper is a surface texture, not a requirement for every scene background.
The scene itself controls setting, palette, lighting, and environment.

v4.2: น่ารัก (kawaii chibi) เฉพาะ "สิ่งมีชีวิต" เท่านั้น; วัตถุ สถานที่ ปรากฏการณ์ เซลล์ อวัยวะ และองค์ประกอบรอบข้างทั้งหมดสมจริง
ตรงข้อเท็จจริง ไม่มีหน้าตา; build_prompt ตัดคำชวนให้น่ารัก (kawaii/chibi/cute/whimsical ฯลฯ) ออกจากคำบรรยายฉาก
เพราะความน่ารักถูกควบคุมจาก STYLE ส่วนสิ่งมีชีวิตเท่านั้น

v4.0: สไตล์ kawaii chibi ตามภาพตัวอย่าง + สั่งภาพเต็มขอบ (full-bleed, no border/frame/margin) เฉพาะใน prompt
(ไม่มีขั้น crop) ตัดคำว่า "cream paper may show / paper margin" ที่เคยชวนให้โมเดลวาดขอบกระดาษออก

v3.8 (phase A): IMAGE_DETAIL_LEVEL = "rich" (default) or "standard" controls how much storybook detail
the style asks for, and how detailed the script writer's image_prompt must be (see 1_generate_script.py).
"""

_STYLE_BASE = (
    "Storybook watercolor illustration, full-bleed edge-to-edge canvas, delicate dark-brown ink outlines, "
    "translucent washes, fine paper grain. "
)
# v4.2: ความน่ารักใช้กับ "สิ่งมีชีวิต" เท่านั้น (คน สัตว์ แมลง สิ่งมีชีวิตขนาดเล็ก)
_STYLE_LIVING = (
    "Only living beings (people, animals, insects, tiny organisms) are kawaii chibi: rounded, big glossy black eyes, "
    "rosy cheeks, chubby, short limbs. "
)
# v4.2: สิ่งไม่มีชีวิตและองค์ประกอบรอบข้างสมจริง ตรงข้อเท็จจริง ไม่มีหน้าตา (เขียนเชิงบวก + สั้น เพราะ prompt ภาพมีเพดานตัวอักษร)
_STYLE_NONLIVING = (
    "Everything else (objects, places, landscapes, phenomena, cells, organs, molecules, planets, machines, surroundings) "
    "is realistic, clear and accurate to science and history, drawn as ordinary faceless things as in real life. "
)
_STYLE_TAIL = (
    "Clean blank surfaces, soft light, pastel tones for characters and natural colors elsewhere. "
)

STYLES = {
    # rich: ภาพมีชั้นหน้า-กลาง-หลัง ตัวละครมีท่าทาง ของประกอบ และบรรยากาศแสง แต่ยังมีจุดโฟกัสเดียว
    "rich": (
        _STYLE_BASE
        + _STYLE_LIVING
        + _STYLE_NONLIVING
        + "Layered depth, expressive poses for living characters, one clear focal point. "
        + _STYLE_TAIL
    ),
    # standard: รายละเอียดปานกลาง กติกา "น่ารักเฉพาะสิ่งมีชีวิต" และเต็มขอบเหมือนกัน
    "standard": (
        _STYLE_BASE
        + _STYLE_LIVING
        + _STYLE_NONLIVING
        + "One clear focal point and a softly painted setting that fills the canvas. "
        + _STYLE_TAIL
    ),
}


def resolve_detail_level() -> str:
    raw = os.getenv("IMAGE_DETAIL_LEVEL", "rich").strip().lower() or "rich"
    if raw not in STYLES:
        print(f"WARNING: IMAGE_DETAIL_LEVEL '{raw}' ไม่ถูกต้อง (ใช้ได้: standard, rich) -> ใช้ rich")
        return "rich"
    return raw


IMAGE_DETAIL_LEVEL = resolve_detail_level()
STYLE = STYLES[IMAGE_DETAIL_LEVEL]

# Shot variety is a suggestion; scenes starting with cross-section/macro skip it (see build_prompt).
SHOTS = [
    "Use a medium shot that shows the characters' poses together with their surroundings.",
    "Use a wide establishing composition with clear foreground, middle ground and background.",
    "Use a low-angle viewpoint when appropriate.",
    "Use a bird's-eye viewpoint when appropriate.",
    "Use a side/profile viewpoint when appropriate.",
    "Use a detailed close-up when the subject benefits from it.",
    "Use an over-the-shoulder or three-quarter viewpoint when appropriate.",
    "Use a balanced environmental composition with layered depth.",
]

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
    identities = [strip_cute_words(i) for i in extract_identities(raw_desc)]
    identities = [i for i in identities if i]
    scene_desc = strip_identity(raw_desc).rstrip(".") if identities else re.sub(r"\s+", " ", raw_desc).rstrip(".")
    # ภาพตัดขวาง/ภาพขยายใกล้กำหนดมุมกล้องเองอยู่แล้ว -> ไม่ใส่ shot ซ้ำให้ชนกัน
    scene_desc = strip_cute_words(scene_desc)
    if re.match(r"(cross-section|close-up macro)", scene_desc, re.I):
        shot = ""
    else:
        shot = SHOTS[max(0, int(scene.get("id", 1)) - 1) % len(SHOTS)]
    identity_instruction = ""
    if identities:
        identity_instruction = (
            "CHARACTER / SUBJECT IDENTITY MUST MATCH EXACTLY: "
            + "; ".join(identities)
            + ". Preserve the same species, anatomy, proportions, base colors, "
              "markings, and distinctive features. Only pose, action, expression, "
              "camera angle, and environment may change as the scene requires."
        )
    # v3.6: ไม่ส่งบทพากย์ (narration) เข้าโมเดลภาพ เพราะ T1 พบว่าโมเดลเอาบทมาเขียนเป็นตัวหนังสือในภาพ
    # (ฉาก 4: ข้อความอังกฤษที่แปลจากบทไทยโผล่ใต้ภาพ) image_prompt บรรยายฉากครบในตัวอยู่แล้ว
    # ลำดับ: ฉาก -> identity -> มุมกล้อง -> สไตล์ (FLUX ให้น้ำหนักข้อความช่วงต้น)
    # The explicit scene prompt wins; shot wording is intentionally non-binding.
    parts = [STYLE, f"Scene: {scene_desc}.", identity_instruction, shot]
    prompt = re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()
    # v4.2: เพดานความยาว prompt ภาพ (FLUX บน Cloudflare รับได้ราว 2048 ตัวอักษร) -> ตัดมุมกล้อง (ไม่บังคับ) ก่อน
    if len(prompt) > MAX_PROMPT_CHARS and shot:
        prompt = re.sub(r"\s+", " ", " ".join(p for p in parts[:3] if p)).strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        print(f"WARNING: image prompt ฉาก {scene.get('id')} ยาว {len(prompt)} ตัวอักษร เกิน {MAX_PROMPT_CHARS} ผู้ให้บริการภาพอาจตัดท้ายข้อความ")
    return prompt
