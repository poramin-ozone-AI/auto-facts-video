# Auto Facts Video (ระบบสร้างคลิปความรู้แปลกๆ อัตโนมัติ ฟรี 100%)

ระบบสร้างวิดีโอสั้นความรู้แปลกๆ ภาษาไทยความละเอียด **1280×720 (16:9)** ความยาวประมาณ **40–90 วินาที** วันละ 1 คลิปอัตโนมัติบน **GitHub Actions** โดยใช้ API ฟรีทั้งหมด

---

## โครงสร้างโปรเจกต์

```text
auto-facts-video/
├── .github/workflows/daily_video.yml   # Workflow ตั้งเวลา 08:00 น. (เวลาไทย) + กดรันทดสอบได้
├── assets/
│   ├── stickman_ref.png                # ชีตตัวละคร (ใช้เป็นต้นแบบเขียน prompt เท่านั้น โค้ดไม่ได้เรียกใช้ไฟล์นี้)
│   └── style_bg_ref.png                # ภาพตัวอย่างสไตล์ (เช่นเดียวกัน)
├── scripts/
│   ├── style.py                        # ข้อความคุมสไตล์ภาพและตัวละคร
│   ├── 1_generate_script.py            # ขั้น 1: สร้างบท JSON (Gemini หลายรุ่น -> Groq สำรอง)
│   ├── 2_generate_voice.py             # ขั้น 2: เสียงพากย์ (Gemini TTS 2 รุ่น -> edge-tts สำรองทั้งคลิป)
│   ├── 3_generate_images.py            # ขั้น 3: ภาพ 16:9 (Cloudflare FLUX -> Cloudflare สำรอง -> Pollinations)
│   ├── 4_render_video.py               # ขั้น 4: ซูมภาพนิ่งช้าๆ + รวมเสียงเป็น output.mp4
│   └── 5_save_history.py               # ขั้น 5: บันทึกหัวข้อที่ใช้แล้ว (ทำหลังคลิปสำเร็จเท่านั้น)
├── output/
│   └── topics_history.txt              # สร้างอัตโนมัติ: บันทึกหัวข้อที่ใช้แล้ว (commit กลับ repo)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 1. การตั้งค่า Secrets บน GitHub

ไปที่ **Settings → Secrets and variables → Actions → New repository secret** แล้วเพิ่ม:

| ชื่อ Secret | แหล่งที่มา | จำเป็นไหม |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio (`aistudio.google.com`) | จำเป็น (เขียนบท + เสียงพากย์) |
| `GROQ_API_KEY` | GroqCloud Console (`console.groq.com`) | แนะนำ (ตัวสำรองเขียนบท) |
| `CLOUDFLARE_API_TOKEN` | Cloudflare Dashboard → Workers AI → Create API Token | จำเป็น (สร้างภาพ) |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare Dashboard → Workers AI | จำเป็น (สร้างภาพ) |

และไปที่ **Settings → Actions → General → Workflow permissions** เลือก **Read and write permissions** แล้วกด **Save**

---

## 2. ตัวแปรที่ปรับแต่งได้ (อยู่ในบล็อก `env:` ของ `.github/workflows/daily_video.yml` แล้ว)

| ตัวแปร | ค่าเริ่มต้น | หน้าที่ |
|---|---|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` | โมเดลเขียนบทหลัก |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.6-flash,gemini-2.5-flash-lite` | รุ่นสำรองของ Gemini (ลองตามลำดับเมื่อรุ่นหลักใช้ไม่ได้/429) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | โมเดลเขียนบทสำรองบน Groq |
| `GEMINI_TTS_MODEL` | `gemini-3.1-flash-tts-preview` | โมเดลเสียงพากย์หลัก |
| `GEMINI_TTS_FALLBACK_MODELS` | `gemini-2.5-flash-preview-tts` | รุ่นเสียงสำรอง (เลือกจากฉากแรก แล้วใช้รุ่นเดียวทั้งคลิป) |
| `GEMINI_VOICE` | `Orus` | เสียงพากย์ชาย (ตัวเลือกอื่น: `Charon`, `Algenib`, `Schedar`, `Fenrir`) |
| `GEMINI_TTS_DELAY` | `31` | วินาทีที่เว้นระหว่างฉาก เพื่อไม่ให้เกินโควตาฟรี |
| `EDGE_VOICE` / `VOICE_RATE` / `VOICE_PITCH` | `th-TH-NiwatNeural` / `-8%` / `-2Hz` | เสียงสำรอง edge-tts |
| `CF_IMAGE_MODEL` | `@cf/black-forest-labs/flux-1-schnell` | โมเดลภาพหลัก |
| `CF_IMAGE_FALLBACK_MODELS` | `@cf/bytedance/stable-diffusion-xl-lightning` | โมเดลภาพสำรองบน Cloudflare |
| `CF_IMAGE_STEPS` | `6` | จำนวนขั้นวาดภาพของ FLUX (1–8) |
| `ENABLE_POLLINATIONS` | `1` | ตัวสำรองภาพสุดท้าย (ไม่ต้องใช้คีย์ แต่ช้าและอาจมีลายน้ำ) ตั้งเป็น `0` เพื่อปิด |

---

## 3. วิธีทดสอบและใช้งาน

1. แท็บ **Actions** → **daily-video** → **Run workflow** (คง `test_images` ติ๊กไว้) แล้วดาวน์โหลด Artifact `debug-or-test-…` มาฟังเสียงและดูภาพตัวอย่าง 2 ฉาก (โหมดนี้ไม่บันทึกหัวข้อ)
2. พอใจแล้ว รันอีกครั้งโดยเอาเครื่องหมายถูก `test_images` ออก จะได้ Artifact `daily-video-…` (`output.mp4`) หลังจากนั้นระบบรันเองทุกวัน 08:00 น.

หัวข้อจะถูกบันทึกลง `output/topics_history.txt` **เฉพาะเมื่อคลิปสำเร็จ** รันที่ล้มเหลวจึงไม่เสียหัวข้อ

---

## 4. ตารางแก้ปัญหาตาม Log ที่พบบ่อย

| อาการ / ข้อความใน Log | สาเหตุ | วิธีแก้ |
|---|---|---|
| `[gemini:...] ใช้ไม่ได้ ข้ามไปตัวถัดไป -> HTTP 404` | Google เปลี่ยน/ปิดชื่อรุ่นโมเดล | ระบบข้ามไปรุ่นสำรอง/Groq เอง แต่ควรแก้ `GEMINI_MODEL` ใน `daily_video.yml` |
| `ทุกรุ่น Gemini TTS ล้มเหลว ... -> สลับไปสร้างใหม่ทั้งคลิปด้วย edge-tts` | โควตา Gemini TTS เต็ม หรือรุ่นถูกปิด | คลิปยังสำเร็จด้วยเสียง `th-TH-NiwatNeural` (วันถัดไปลอง Gemini ใหม่เอง) |
| `[cloudflare:...] ใช้ไม่ได้ต่อไปในการรันนี้` | โควตา/ความจุ Cloudflare เต็ม (429) หรือโทเคนผิด (401/403) | ระบบสลับไปรุ่นสำรองเอง ตรวจ Secrets ถ้าเป็น 401/403 โควตารีเซ็ต 00:00 UTC |
| `WARNING: มีภาพจาก Pollinations` | ภาพบางฉากมาจากตัวสำรองสุดท้าย | เปิดดูภาพก่อนโพสต์ว่ามีลายน้ำ/สไตล์ต่างไหม |
| `สร้างภาพไม่สำเร็จทุกผู้ให้บริการ` | ภาพล้มเหลวทุกตัว | ดู log ว่าแต่ละตัวล้มเพราะอะไร แล้วรันใหม่ |
| `Permission denied to github-actions[bot]` ตอน push | ยังไม่ได้เปิดสิทธิ์เขียนให้ Actions | **Settings → Actions → General** เลือก **Read and write permissions** |
