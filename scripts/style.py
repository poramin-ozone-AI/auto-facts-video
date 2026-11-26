"""ข้อความสไตล์คงที่ที่ขั้น 3 (สร้างภาพ) จะนำไปต่อหน้า image_prompt ของทุกฉาก
ถอดจาก assets/stickman_ref.png และ assets/style_bg_ref.png
"""

STYLE = (
    "children's crayon and colored pencil drawing on textured off-white paper, "
    "bold black hand-drawn outlines, bright saturated colors, simple flat composition, "
    "16:9 landscape, no text, no letters, no watermark"
)

STICKMAN = (
    "a stickman character with a large round white head, big black oval eyes, "
    "a spiky mohawk of alternating bright green and white strokes, thin black stick body and limbs, "
    "small black blob hands and black oval shoes, expressive face, centered framing"
)


def build_prompt(scene: dict) -> str:
    """ประกอบ prompt ภาพตามชนิดของฉาก (stickman หรือ object)
    แยกไว้เป็นจุดเดียวเพื่อให้ปรับสไตล์หรือสลับวิธีสร้างภาพในอนาคตได้ง่ายตามสเปกหัวข้อ 7
    """
    scene_desc = scene["image_prompt"].strip().rstrip(".")
    if scene["type"] == "stickman":
        return (
            f"{STYLE}. {STICKMAN}. Scene: {scene_desc}. "
            "All people in the scene are stickmen of the exact same style, centered with safe margins."
        )
    return (
        f"{STYLE}. Scene: {scene_desc}. "
        "No people, no human figures, no stickman; the animal or object is the sole clear focus in the center."
    )
