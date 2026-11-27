import re

"""Style and scene prompt builder for varied watercolor illustrations.

Cream watercolor paper is a surface texture, not a requirement for every scene background.
The scene itself controls setting, palette, lighting, and environment.
"""
STYLE = (
    "Whimsical children's-book watercolor illustration, delicate thin black ink outlines, "
    "translucent layered watercolor washes and subtle natural pigment texture. "
    "Keep a gentle handmade storybook quality; use cute expressive design only when it suits "
    "the subject. The cream paper grain may show subtly in the painted texture, but do not force "
    "a cream-colored background: paint a setting, atmosphere, and palette appropriate to the scene. "
    "Vary composition, camera distance, viewpoint, lighting, and environmental details according "
    "to the subject. Make the narrated subject unmistakably clear and visually dominant without "
    "always placing it in the exact center. Use a clean visual hierarchy and avoid unnecessary clutter. "
    "No text, letters, numbers, labels, speech bubbles, logos, or watermark. "
    "Not photorealistic, not 3D, not flat vector art."
)

# Shot variety is a suggestion; scenes starting with cross-section/macro skip it (see build_prompt).
SHOTS = [
    "Use a medium close-up composition.",
    "Use a wide establishing composition that clearly explains the setting.",
    "Use a low-angle viewpoint when appropriate.",
    "Use a bird's-eye viewpoint when appropriate.",
    "Use a side/profile viewpoint when appropriate.",
    "Use a detailed close-up when the subject benefits from it.",
    "Use an over-the-shoulder or three-quarter viewpoint when appropriate.",
    "Use a balanced environmental composition with clear foreground and background.",
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
            " CHARACTER / SUBJECT IDENTITY MUST MATCH EXACTLY: "
            + "; ".join(identities)
            + ". Preserve the same species, anatomy, proportions, base colors, "
              "markings, and distinctive features. Only pose, action, expression, "
              "camera angle, and environment may change as the scene requires."
        )
    # The explicit scene prompt wins; shot wording is intentionally non-binding.
    return (
        f"{STYLE} {shot} "
        f"Show one clear primary idea that directly illustrates this narration: "
        f"{str(scene.get('narration', '')).strip()} "
        f"Scene description: {scene_desc}. {identity_instruction}"
    ).replace("  ", " ")
