"""ขั้น 0: ตรวจว่าชื่อโมเดล Gemini ที่ตั้งไว้ยังอยู่ในรายการของ API หรือไม่ (เตือนอย่างเดียว ไม่ทำให้ workflow ล้ม)

ที่มา: เคยมีกรณีโมเดลเสียงถูกปิดโดยไม่รู้ตัวแล้วระบบสลับไปตัวสำรองเงียบๆ
ข้อควรระวัง: "อยู่ในรายการ" ไม่ได้การันตีว่าใช้งานได้จริง (บัญชีใหม่อาจได้ 404 กับบางรุ่น)
แต่ "ไม่อยู่ในรายการ" เป็นสัญญาณชัดว่าควรแก้ชื่อรุ่นใน env ของ workflow
"""
import os
import sys
import requests


def csv(name: str, default: str) -> list[str]:
    return [m.strip() for m in os.getenv(name, default).split(",") if m.strip()]


def main():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        print("ข้ามการตรวจชื่อโมเดล: ไม่มี GEMINI_API_KEY")
        return
    names, token = set(), None
    try:
        for _ in range(10):
            params = {"pageSize": 1000}
            if token:
                params["pageToken"] = token
            r = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": key},
                params=params,
                timeout=30,
            )
            print(f"[models.list] HTTP {r.status_code}")
            if r.status_code != 200:
                print(f"WARNING: เรียกรายชื่อโมเดลไม่สำเร็จ ข้ามการตรวจ: {r.text[:200]}")
                return
            body = r.json()
            names |= {m.get("name", "").removeprefix("models/") for m in body.get("models", [])}
            token = body.get("nextPageToken")
            if not token:
                break
    except Exception as e:
        print(f"WARNING: ตรวจชื่อโมเดลไม่สำเร็จ ({type(e).__name__}: {e}) ข้ามไป")
        return

    wanted = {
        "เขียนบท": [os.getenv("GEMINI_MODEL", "gemini-3.8-flash")]
        + csv("GEMINI_FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.5-flash-lite"),
        "เสียงพากย์": [os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")]
        + csv("GEMINI_TTS_FALLBACK_MODELS", ""),
    }
    problems = 0
    for purpose, models in wanted.items():
        for m in models:
            if m in names:
                print(f"OK  {purpose}: {m}")
            else:
                problems += 1
                print(f"WARNING: {purpose}: ไม่พบ '{m}' ในรายการโมเดลของ API -> ตรวจชื่อรุ่นใน env ของ daily_video.yml")
    if problems == 0:
        print("ชื่อโมเดลทั้งหมดอยู่ในรายการ")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # ไม่ให้ขั้นนี้ทำให้ workflow ล้ม
        print(f"WARNING: ขั้น 0 ผิดพลาด ข้ามไป: {type(e).__name__}: {e}")
    sys.exit(0)
