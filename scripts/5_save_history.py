"""ขั้น 5: บันทึกหัวข้อลง output/topics_history.txt (เรียกหลังเรนเดอร์คลิปสำเร็จเท่านั้น)

แยกออกมาจากขั้น 1 เพื่อไม่ให้หัวข้อที่ทำคลิปไม่สำเร็จถูกนับว่าใช้แล้ว
"""
import json
import pathlib
import re
import sys

OUT = pathlib.Path("output")
HISTORY = OUT / "topics_history.txt"


def norm(t: str) -> str:
    return re.sub(r"\s+", "", t).lower()


def main():
    sp = OUT / "script.json"
    if not sp.exists():
        sys.exit("ไม่พบ output/script.json")
    topic = str(json.loads(sp.read_text(encoding="utf-8")).get("topic", "")).replace("\n", " ").strip()
    if not topic:
        sys.exit("script.json ไม่มีหัวข้อ")
    existing = HISTORY.read_text(encoding="utf-8").splitlines() if HISTORY.exists() else []
    if norm(topic) in {norm(x) for x in existing}:
        print(f"หัวข้อนี้มีใน history อยู่แล้ว: {topic}")
        return
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(topic + "\n")
    print(f"บันทึกหัวข้อแล้ว: {topic}")


if __name__ == "__main__":
    main()
