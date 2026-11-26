"""ข้อความสไตล์คงที่ที่ขั้น 3 (สร้างภาพ) จะนำไปต่อหน้า image_prompt ของทุกฉาก
ถอดจาก assets/stickman_ref.png และ assets/style_bg_ref.png
"""

STYLE = (
    "children's crayon and colored pencil drawing on textured off-white paper, "
    "bold black hand-drawn outlines, bright saturated colors, visible crayon strokes, "
    "full colorful background scene filling the entire frame, wide 16:9 landscape composition, "
    "entire subject fully inside the frame with generous margins on all sides, nothing cut off, "
    "no text, no letters, no watermark"
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
            "Match the character from image 1 and the crayon style from image 2. Full body visible from head to shoes. "
            "The green and white mohawk is always fully visible, never covered by a hat or helmet. "
            "All people in the scene are stickmen of the exact same style."
        )
    return (
        f"{STYLE}. Scene: {scene_desc}. "
        "Match the crayon style of image 1. No people, no human figures, no stickman; "
        "the whole animal or object is visible and is the sole clear focus in the center."
    )
