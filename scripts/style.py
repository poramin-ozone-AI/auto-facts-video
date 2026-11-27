import os
import re

"""Style and scene prompt builder for varied watercolor illustrations.

Cream watercolor paper is a surface texture, not a requirement for every scene background.
The scene itself controls setting, palette, lighting, and environment.

v4.0: สไตล์ kawaii chibi ตามภาพตัวอย่าง + สั่งภาพเต็มขอบ (full-bleed, no border/frame/margin) เฉพาะใน prompt
(ไม่มีขั้น crop) ตัดคำว่า "cream paper may show / paper margin" ที่เคยชวนให้โมเดลวาดขอบกระดาษออก

v3.8 (phase A): IMAGE_DETAIL_LEVEL = "rich" (default) or "standard" controls how much storybook detail
the style asks for, and how detailed the script writer's image_prompt must be (see 1_generate_script.py).
"""

_STYLE_BASE = (
    "Kawaii chibi storybook watercolor illustration, full-bleed edge-to-edge painted canvas. "
    "Cute rounded characters with large glossy black eyes, tiny highlights, rosy cheeks, simple mouths, "
    "chubby proportions and short limbs. Delicate dark-brown ink outlines, translucent warm pastel washes, "
    "and fine watercolor paper grain across the entire scene. "
)
_STYLE_TAIL = (
    "Clean, unmarked surfaces with pictorial storytelling; keep walls, fabrics and props visually blank. "
    "Hand-painted 2D storybook illustration with soft atmospheric light and a cohesive pastel palette. "
)

STYLES = {
    # rich: ภาพมีชั้นหน้า-กลาง-หลัง ตัวละครมีท่าทาง ของประกอบ และบรรยากาศแสง แต่ยังมีจุดโฟกัสเดียว
    "rich": (
        _STYLE_BASE
        + "Layered foreground, middle ground and background; expressive poses and a few meaningful props support one clear focal point. "
        + _STYLE_TAIL
    ),
    # standard: รายละเอียดปานกลาง แต่ยังเป็นสไตล์น่ารักและเต็มขอบเหมือนกัน
    "standard": (
        _STYLE_BASE
        + "A clear focal point, balanced supporting details, and a softly painted setting that fills the canvas. "
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


def build_prompt(scene: dict) -> str:
    raw_desc = str(scene.get("image_prompt", "")).strip()
    identities = extract_identities(raw_desc)
    scene_desc = strip_identity(raw_desc).rstrip(".") if identities else re.sub(r"\s+", " ", raw_desc).rstrip(".")
    # ภาพตัดขวาง/ภาพขยายใกล้กำหนดมุมกล้องเองอยู่แล้ว -> ไม่ใส่ shot ซ้ำให้ชนกัน
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
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()
