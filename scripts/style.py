"""ข้อความสไตล์คงที่ที่ขั้น 3 (สร้างภาพ) จะนำไปต่อหน้า image_prompt ของทุกฉาก

สไตล์: สีน้ำ + เส้นหมึกดำบาง บนกระดาษครีมมีลาย (ถอดจากภาพตัวอย่างเป็น "ข้อความล้วน" ไม่ส่งภาพอ้างอิงให้โมเดล
เพื่อกันไม่ให้ชิ้นส่วนของภาพตัวอย่างหลุดเข้ามาในภาพใหม่)
ไม่มีการล็อกตัวละคร: แต่ละฉากเป็นภาพอิสระ จะเป็นสัตว์ สิ่งของ ธรรมชาติ หรือคนก็ได้
"""

STYLE = (
    "Children's book watercolor illustration with fine black ink outlines, "
    "soft translucent watercolor washes with visible bleeding edges, on warm cream textured watercolor paper. "
    "Cute expressive characters with big round shiny eyes, gentle muted colors with warm orange and soft blue accents, "
    "subtle hand-drawn shading. Loose watercolor splashes fading out softly toward the edges of the paper. "
    "Small decorative details such as tiny four-point sparkles, short motion lines, "
    "and an optional small round speech bubble containing only a single \"?\" or \"!\" symbol. "
    "Vertical 9:16 portrait composition, the main subject centered with generous margins, "
    "entire subject fully inside the frame, nothing cut off. "
    "No words, no letters, no numbers, no watermark. Not a photo, not 3D, not flat digital vector art."
)


def build_prompt(scene: dict) -> str:
    """ประกอบ prompt ภาพ: บล็อกสไตล์ + คำบรรยายฉาก (แยกไว้จุดเดียวเพื่อปรับสไตล์ในอนาคตได้ง่าย)"""
    scene_desc = scene["image_prompt"].strip().rstrip(".")
    return f"{STYLE} Scene: {scene_desc}."
