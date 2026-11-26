"""ข้อความสไตล์คงที่ที่ขั้น 3 (สร้างภาพ) จะนำไปต่อหน้า image_prompt ของทุกฉาก

สไตล์: สีน้ำ + เส้นหมึกดำบาง บนกระดาษครีมมีลาย (ถอดจากภาพตัวอย่างเป็น "ข้อความล้วน" ไม่ส่งภาพอ้างอิงให้โมเดล
เพื่อกันไม่ให้ชิ้นส่วนของภาพตัวอย่างรั่วเข้าภาพใหม่)
ไม่มีการล็อกตัวละคร: แต่ละฉากเป็นภาพอิสระ จะเป็นสัตว์ สิ่งของ ธรรมชาติ หรือคนก็ได้
มุมภาพ: build_prompt สลับมุมกล้องตามเลขฉาก (SHOTS) เพื่อไม่ให้ทุกภาพเป็นวัตถุกลางภาพแบบเดียวกัน
"""

STYLE = (
    "Children's book watercolor illustration with fine black ink outlines, "
    "soft translucent watercolor washes with visible bleeding edges, on warm cream textured watercolor paper. "
    "Cute expressive main character or subject with big round shiny eyes; only the main character has eyes, "
    "no faces on small dots, bubbles, droplets or background objects. "
    "Gentle muted colors with warm orange and soft blue accents, subtle hand-drawn shading. "
    "Loose watercolor splashes fading out softly toward the edges of the paper. "
    "Small decorative details such as tiny four-point sparkles and short motion lines. "
    "Vertical 9:16 portrait composition, the main subject centered and large, filling about 60 to 70 percent "
    "of the frame height, entire subject fully inside the frame, nothing cut off. "
    "No words, no letters, no numbers, no watermark. Not a photo, not 3D, not flat digital vector art."
)

# มุมกล้องที่สลับตามเลขฉาก (ฉาก 1 = มุมใกล้ปานกลางเพื่อดึงสายตา)
SHOTS = [
    "Medium close-up view.",
    "Wide view showing the whole scene, with the main subject still large and prominent.",
    "Low-angle view looking up at the main subject.",
    "Bird's-eye view looking down from above.",
    "Side view with the main subject in profile.",
    "Close-up view filling most of the frame.",
]


def build_prompt(scene: dict) -> str:
    """ประกอบ prompt ภาพ: บล็อกสไตล์ + มุมกล้อง + คำบรรยายฉาก (แยกไว้จุดเดียวเพื่อปรับสไตล์ในอนาคตได้ง่าย)
    ถ้าคำบรรยายฉากสั่งภาพตัดขวาง (cross-section/cutaway) อยู่แล้ว จะไม่ใส่มุมกล้องทับ"""
    scene_desc = scene["image_prompt"].strip().rstrip(".")
    low = scene_desc.lower()
    if "cross-section" in low or "cross section" in low or "cutaway" in low:
        shot = ""
    else:
        idx = (int(scene.get("id", 1)) - 1) % len(SHOTS)
        shot = SHOTS[idx] + " "
    return f"{STYLE} {shot}Scene: {scene_desc}."
