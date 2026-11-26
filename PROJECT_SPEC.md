# สเปกและสรุปงานฉบับสมบูรณ์: ระบบสร้างคลิปความรู้แปลกๆ อัตโนมัติ (ฟรี 100%)

> เอกสารนี้รวบรวมทุกอย่างที่ตกลงและทำมาทั้งหมดจากการพูดคุย (รวมสเปกเดิม โค้ดที่ปรับปรุงล่าสุด ข้อจำกัดจากการใช้งานบนมือถือ และวิธีสร้างระบบแบบคลิกต่อคลิก) เพื่อนำไปใช้สร้างหรือทำงานต่อในแชทใหม่ได้ทันที

---

## 1. เป้าหมายและภาพรวมระบบ
- **เนื้อหา:** คลิปความรู้แปลกๆ ที่คนส่วนใหญ่ไม่รู้ ภาษาไทย (ผู้ใช้ดาวน์โหลดไฟล์ไปโพสต์ลง YouTube Shorts / TikTok เอง)
- **ความยาวเป้าหมาย:** ประมาณ 40 วินาที – 1 นาที 30 วินาที (ยืดหยุ่นตามความยาวเสียงพากย์จริง)
- **ความถี่:** วันละ 1 คลิป อัตโนมัติผ่าน GitHub Actions
- **งบประมาณ:** ฟรี 100%
- **ผลลัพธ์สุดท้าย:** ไฟล์วิดีโอ `output/output.mp4` ความละเอียด **1280×720 (16:9 แนวนอน)**, 30 fps, H.264 + AAC
- **การรับไฟล์:** ผู้ใช้เข้า GitHub → แท็บ **Actions** → เลือกรอบที่รัน → ดาวน์โหลดไฟล์จาก **Artifacts** (ไม่ทำระบบส่งเข้า Android อัตโนมัติ ไม่ใช้ Telegram)

---

## 2. การตัดสินใจที่ล็อกไว้ (ห้ามเปลี่ยนโดยไม่ถามผู้ใช้)
| หัวข้อ | การตัดสินใจ |
|---|---|
| ที่รัน | GitHub Actions (`cron` วันละ 1 รอบ) + Python 3.12 + FFmpeg |
| สัดส่วนภาพ | 16:9 แนวนอน (ผู้ใช้รับทราบแล้วว่าเมื่อโพสต์ Shorts/TikTok แนวตั้ง ภาพจะเล็กลงบนมือถือ) |
| ลักษณะภาพและ motion | ภาพนิ่ง + ซูมเข้าช้าๆ (`zoompan`) เปลี่ยนฉากตามบทพากย์ |
| สไตล์ภาพ | ดินสอสี/สีเทียน เส้นขอบดำ สีสด บนกระดาษมีลาย |
| ตัวละครหลัก | Stickman หัวกลมขาว ผมโมฮอว์กเขียวสลับขาว (อ้างอิงจาก `assets/stickman_ref.png`) |
| ฉากมีคน/ฝูงชน | สร้างตัวละครเสริมได้ แต่ **ต้องเป็น Stickman สไตล์เดียวกันทั้งหมด** |
| ฉากโชว์สัตว์/สิ่งของแปลกๆ | **ห้ามใส่ Stickman หรือคน** เน้นวัตถุ/สัตว์ให้ชัด |
| เสียงพากย์ | **เสียงผู้ชาย** นุ่มนวล หนักแน่น น่าเชื่อถือ จังหวะไม่รีบ |
| ผู้ให้บริการเสียง | **Gemini TTS เป็นตัวหลัก** (เสียงเริ่มต้น `Orus`; รุ่น `gemini-3.1-flash-tts-preview` สำรอง `gemini-2.5-flash-preview-tts` เลือกจากฉากแรกแล้วใช้รุ่นเดียวทั้งคลิป), **`edge-tts` เป็นตัวสำรองทั้งคลิป** (`th-TH-NiwatNeural`) |
| ซับไตเติล | **ไม่มี** |
| เพลงประกอบ | **ไม่มี** |
| ไฟล์ชื่อคลิป/แฮชแท็ก | **ไม่ต้องมี** |
| ขั้นตอนตรวจข้อเท็จจริงแยก | **ไม่ต้องมี** (ผู้ใช้ตรวจเองก่อนโพสต์ แต่ prompt สั่งให้ AI เลือกเฉพาะข้อเท็จจริงที่ตรวจสอบได้) |
| ส่งไฟล์ลง Android | **ไม่ทำ** ผู้ใช้ดาวน์โหลดจาก GitHub Actions Artifacts เอง |

---

## 3. กติกาการทำงาน
1. ง่ายที่สุดและใช้งานได้จริงในระยะยาว
2. **ห้ามเดามั่ว** ให้ตรวจจาก log, HTTP status, ข้อความตอบกลับจาก API และสถานะไฟล์ก่อนระบุสาเหตุเสมอ
3. แก้ซ้ำแล้วไม่ผ่าน → เปลี่ยนไปวิธีหรือโมเดลฟรีที่ง่ายและเสถียรกว่าทันที
4. ต้องมีจุดสลับ/สำรองผู้ให้บริการเมื่อโควตาเต็มหรือคำตอบผิดรูปแบบ
5. **ตรวจข้อมูลขั้นกลางทุกขั้น (validate)** ถ้าไม่ผ่านให้ workflow ล้มพร้อม log ที่อ่านเข้าใจง่าย ห้ามปล่อยคลิปเสียออกมา
6. ทดสอบทีละขั้น/โหมดทดสอบก่อนเปิดใช้เต็มระบบ
7. ก่อนเขียนหรือแก้โค้ดที่เรียก API ภายนอก ให้ตรวจสอบชื่อโมเดล โควตา และรูปแบบ API ล่าสุดเสมอ

---

## 4. ผู้ให้บริการ API, โควตา และตัวแปร Environment
| งาน | ผู้ให้บริการหลัก | ผู้ให้บริการสำรอง | หมายเหตุ / ตัวแปร Env |
|---|---|---|---|
| เขียนบท | Gemini API (`gemini-2.5-flash` -> รุ่นสำรอง `GEMINI_FALLBACK_MODELS`) | Groq (`openai/gpt-oss-120b`) | สลับทันทีเมื่อเจอ `429/404/403/400`; ปรับผ่าน `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS`, `GROQ_MODEL` |
| เสียงพากย์ | Gemini TTS (`gemini-3.1-flash-tts-preview`, สำรอง `gemini-2.5-flash-preview-tts`, เสียง `Orus`) | `edge-tts` (`th-TH-NiwatNeural`) | เว้นระยะ ~31 วิ/ฉาก; ปรับผ่าน `GEMINI_TTS_MODEL`, `GEMINI_TTS_FALLBACK_MODELS`, `GEMINI_VOICE`, `GEMINI_TTS_DELAY`, `EDGE_VOICE`, `VOICE_RATE`, `VOICE_PITCH` |
| สร้างภาพ | Cloudflare Workers AI (`@cf/black-forest-labs/flux-1-schnell`) | Cloudflare `@cf/bytedance/stable-diffusion-xl-lightning` -> Pollinations (ไม่ใช้คีย์ อาจมีลายน้ำ) ; ทางเลือกเรื่องหน้าตาตัวละครดูหัวข้อ 7 | โควตาฟรี 10,000 Neurons/วัน; ปรับผ่าน `CF_IMAGE_MODEL`, `CF_IMAGE_FALLBACK_MODELS`, `CF_IMAGE_STEPS`, `ENABLE_POLLINATIONS` |

**Secrets ที่ต้องตั้งบน GitHub Actions (4 ตัว):**
- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

---

## 5. โครงสร้าง Repository
```text
auto-facts-video/
├── .github/
│   └── workflows/
│       └── daily_video.yml
├── assets/
│   ├── stickman_ref.png        # ชีตตัวละคร Stickman ผมโมฮอว์กเขียว-ขาว
│   └── style_bg_ref.png        # ภาพตัวอย่างสไตล์ดินสอสี/สีเทียน (ฉากชายหาด)
├── output/
│   ├── .gitkeep
│   └── topics_history.txt      # สร้างอัตโนมัติ: หัวข้อที่ใช้แล้ว (commit กลับ repo หลังคลิปสำเร็จเท่านั้น)
├── scripts/
│   ├── style.py
│   ├── 1_generate_script.py
│   ├── 2_generate_voice.py
│   ├── 3_generate_images.py
│   ├── 4_render_video.py
│   └── 5_save_history.py       # บันทึกหัวข้อหลังเรนเดอร์สำเร็จ
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 6. รายละเอียดการทำงานแต่ละส่วนและ Prompt ที่ใช้

### 6.0 สัญญาข้อมูล `output/script.json`
ทุกสคริปต์อ่านและอัปเดตไฟล์ `output/script.json` ตามโครงสร้างนี้:
```json
{
  "topic": "หัวข้อสั้นๆ",
  "title": "ชื่อคลิป",
  "provider": "gemini|groq",
  "scenes": [
    {
      "id": 1,
      "narration": "ข้อความพากย์",
      "type": "stickman|object",
      "image_prompt": "English, ภาพเดียว ชัดเจน",
      "audio": "output/audio/scene_01.mp3",
      "duration": 7.42,
      "image": "output/images/scene_01.png"
    }
  ],
  "total_duration": 62.3,
  "voice_provider": "gemini|edge"
}
```

### 6.1 ขั้นที่ 1: `scripts/1_generate_script.py`
- เรียก Gemini (`responseMimeType: application/json`) เป็นหลัก หากล้มเหลวหรือเจอ `429` ให้สลับไป Groq (ลองสูงสุด 3 รอบต่อผู้ให้บริการ)
- **Prompt เขียนบท:** สั่งให้เป็นนักเขียนบทคลิปสั้น *"ความรู้แปลกๆ ที่คนส่วนใหญ่ไม่รู้"* ภาษาไทย เน้นข้อเท็จจริงที่ตรวจสอบได้จริงทางวิทยาศาสตร์ ประวัติศาสตร์ ธรรมชาติ หรือจิตวิทยา ห้ามเดาหรือแต่งเอง ห้ามซ้ำหัวข้อ 60 เรื่องล่าสุดใน `output/topics_history.txt` เปิดด้วย 1–2 ประโยคดึงดูด ปิดด้วยประโยคสรุปสั้นๆ โทนนุ่มนวล หนักแน่น น่าเชื่อถือ ความยาวรวม **450–1,400 ตัวอักษร** แบ่งเป็น **6–12 ฉาก** แต่ละฉากมี `image_prompt` ภาษาอังกฤษบรรยายภาพเดียว วางจุดเด่นกลางภาพ แยก `type` เป็น `"stickman"` (มีคน/เหตุการณ์/การทดลอง ตัวละครทั้งหมดต้องเป็น stickman) หรือ `"object"` (สัตว์/สิ่งของ/ธรรมชาติ/วัตถุแปลกๆ ล้วนๆ ห้ามมีคนหรือ stickman) และห้ามมีตัวหนังสือ/ตัวเลขในภาพ
- **Validate:** ตรวจว่ามี `topic`, `title`, `scenes` ครบ จำนวนฉาก 6–12 ทุกฉากมี `narration` ไม่ว่าง `type` เป็น `stickman` หรือ `object` `image_prompt` ยาว ≥ 15 ตัวอักษร และความยาวบทรวมอยู่ระหว่าง 450–1,400 ตัวอักษร
- ตรวจหัวข้อซ้ำกับ history ด้วย (ซ้ำ = ไม่ผ่าน ลองใหม่) ลำดับลอง: Gemini `GEMINI_MODEL` -> `GEMINI_FALLBACK_MODELS` -> Groq
- เมื่อผ่านจะเขียน `output/script.json` เท่านั้น **ไม่บันทึกหัวข้อลง history ในขั้นนี้** (ย้ายไปขั้น 5 เพื่อไม่ให้หัวข้อที่ทำคลิปไม่สำเร็จถูกนับว่าใช้แล้ว)

### 6.2 ขั้นที่ 2: `scripts/2_generate_voice.py`
- สร้างเสียงทีละฉากเพื่อวัดความยาวจริงของแต่ละฉาก
- **Gemini TTS เป็นหลัก:** ลองรุ่น `GEMINI_TTS_MODEL` ก่อน ถ้าฉากแรกใช้ไม่ได้ (404/403/429 ครบรอบ) ลองรุ่นใน `GEMINI_TTS_FALLBACK_MODELS` เมื่อฉากแรกสำเร็จจะล็อกรุ่นนั้นตลอดคลิป ตั้งต้นที่เสียง `Orus` เว้นระยะห่างระหว่างฉาก 31 วินาที (`GEMINI_TTS_DELAY`) เพื่อไม่ให้เกินโควตาฟรี (~2 RPM) กรณีเจอ `429` จะหน่วงรอและลองใหม่สูงสุด 3 รอบต่อฉาก
- **Prompt / คำสั่งเสียง Gemini TTS:** ครอบ `narration` ของแต่ละฉากด้วยคำสั่ง:
  `"อ่านออกเสียงภาษาไทยด้วยน้ำเสียงผู้ชายผู้บรรยายสารคดี ที่นุ่มนวล หนักแน่น น่าเชื่อถือ จังหวะพอดี ไม่รีบ ชัดถ้อยชัดคำ โดยอ่านเฉพาะข้อความด้านล่างนี้เท่านั้น ห้ามพูดคำสั่งนี้:\n{narration}"`
- แปลง audio bytes จาก `inlineData` (รองรับทั้ง PCM 24kHz 16-bit mono และ audio container) เป็น MP3 ด้วย `ffmpeg`
- **Fallback ทั้งคลิปด้วย `edge-tts`:** หากฉากใดฉากหนึ่งล้มเหลวครบโควตา จะล้างไฟล์เสียงเดิมใน `output/audio/` แล้วสร้างใหม่ทั้งหมดตั้งแต่ฉากแรกด้วย `edge-tts` (`th-TH-NiwatNeural`, rate `-8%`, pitch `-2Hz`) เพื่อไม่ให้เสียงคนละคนปนกันในคลิปเดียว
- **Validate:** ตรวจขนาดไฟล์ > 1,000 bytes ความยาวแต่ละฉาก > 0.3 วินาที และความยาวรวมอยู่ในช่วงปลอดภัย 15–150 วินาที (แจ้งเตือนใน log หากนอกช่วง 35–95 วินาที) บันทึก `audio`, `duration`, `total_duration` และ `voice_provider` ลง `output/script.json`

### 6.3 ขั้นที่ 3: `scripts/style.py` และ `scripts/3_generate_images.py`
- **`STYLE`:** `"children's crayon and colored pencil drawing on textured off-white paper, bold black hand-drawn outlines, bright saturated colors, simple flat composition, 16:9 landscape, no text, no letters, no watermark"`
- **`STICKMAN`:** `"a stickman character with a large round white head, big black oval eyes, a spiky mohawk of alternating bright green and white strokes, thin black stick body and limbs, small black blob hands and black oval shoes, expressive face, centered framing"`
- **`build_prompt(scene)`:**
  - ถ้า `type == "stickman"`: ต่อ `STYLE` + `STICKMAN` + `Scene: {image_prompt}` + `"All people in the scene are stickmen of the exact same style, centered with safe margins."`
  - ถ้า `type == "object"`: ต่อ `STYLE` + `Scene: {image_prompt}` + `"No people, no human figures, no stickman; the animal or object is the sole clear focus in the center."`
- **ลำดับผู้ให้บริการภาพ:** Cloudflare FLUX.1 schnell -> Cloudflare รุ่นสำรอง (`CF_IMAGE_FALLBACK_MODELS`) -> Pollinations (หน่วง 16 วิ/ภาพ อาจมีลายน้ำ ปิดได้ด้วย `ENABLE_POLLINATIONS=0`) ตัวที่เจอ 429/401/403/404 จะถูกข้ามตลอดการรันที่เหลือ และบันทึก `image_provider` ลง `script.json` (ถ้าใช้หลายตัวในคลิปเดียวจะมี WARNING ใน log) ครอปกลางให้เป็นสัดส่วน 16:9 และปรับขนาดเป็น **1280×720** ด้วย `ffmpeg`
- รองรับโหมด `--test`: เลือกสร้างเฉพาะ 2 ฉาก (1 ฉาก `stickman` + 1 ฉาก `object`) โดยไม่เขียนทับ `output/script.json`
- **Validate:** ตรวจขนาดไฟล์ > 5,000 bytes และขนาดภาพสุดท้ายต้องเป็น 1280×720

### 6.4 ขั้นที่ 4: `scripts/4_render_video.py`
- ขยายภาพต้นฉบับเป็น `2560×1440` ก่อนเข้า `zoompan` เพื่อลดอาการสั่น/กระตุกของซับพิกเซล
- ซูมเข้าช้าๆ (`1.00 -> 1.13`) ตลอด `duration` ของแต่ละฉากที่ 30 fps พร้อมสลับจุดโฟกัสระหว่างฉาก (ฉาก `stickman` เน้นโฟกัสช่วงตัวละคร)
- รวมคลิปและเสียงของทุกฉากเป็น `output/output.mp4` (H.264 `yuv420p` + AAC)
- **Validate:** ตรวจด้วย `ffprobe` ว่ามีทั้ง video และ audio stream ขนาด `1280×720` ขนาดไฟล์ ≥ 50 KB และความยาวจริงต่างจาก `total_duration` ไม่เกิน 0.5 วินาที

### 6.5 Workflow `.github/workflows/daily_video.yml`
- ตั้งเวลา `cron: "0 1 * * *"` (01:00 UTC = 08:00 น. เวลาไทย) และ `workflow_dispatch` พร้อม input `test_images` (boolean, default `true`)
- มี `permissions: contents: write` เพื่อ commit `output/topics_history.txt` กลับเข้า repo **หลังเรนเดอร์สำเร็จและอัปโหลด artifact แล้ว** (ขั้น 5; โหมดทดสอบและรันที่ล้มเหลวไม่บันทึกหัวข้อ) ทั้งเพื่อกันหัวข้อซ้ำและรักษาความเคลื่อนไหวของ repo
- ตัวแปรปรับแต่งทั้งหมดอยู่ในบล็อก `env:` ของไฟล์ workflow
- อัปโหลด artifact: เมื่อรันเต็มสำเร็จจะได้ `daily-video-<run_number>` (`output/output.mp4` และ `output/script.json`, เก็บ 14 วัน) และเมื่อรันโหมดทดสอบหรือล้มเหลวจะได้ `debug-or-test-<run_number>` (เก็บ 7 วัน)

---

## 7. ประเด็นค้างอยู่และทางเลือกเมื่อทดสอบภาพ FLUX (สเปกหัวข้อ 9)
เนื่องจาก FLUX.1 schnell รับเฉพาะข้อความและไม่รับภาพอ้างอิง หน้าตา Stickman อาจ "คล้าย" แต่ไม่เหมือนเป๊ะทุกภาพ (ไฟล์ใน `assets/` ใช้เป็นต้นแบบเขียน prompt เท่านั้น โค้ดไม่ได้เรียกใช้; ทางที่ B ยังไม่มีโค้ด จะทำเมื่อผลทดสอบจริงแย่เท่านั้น):
- **ถ้าผ่าน (หน้าตาและสไตล์ใกล้เคียงพอ):** ใช้ prompt ตาม `style.py` ต่อได้เลย
- **ถ้าเพี้ยนมาก:**
  - **ทางที่ A:** เปลี่ยนไปใช้โมเดลภาพที่รับภาพอ้างอิงได้ (ต้องตรวจโควตาฟรีของ API นั้นก่อนว่าไม่ต้องผูกบิล)
  - **ทางที่ B:** ตัดท่าทาง Stickman จากชีต `assets/stickman_ref.png` เป็น PNG พื้นหลังโปร่งใส แล้ววางซ้อนบนฉากหลังที่ AI สร้าง (โดยสั่งฉากหลังว่าห้ามมีคน) พร้อมกำหนดกติกาเลือกท่าตามอารมณ์ของฉาก
- **ถ้าปัญหาอยู่ที่ครอปหรือขนาด:** ปรับ prompt หรือสูตรครอปก่อน โดยไม่ต้องรื้อวิธีทั้งหมด

---

## 8. ข้อจำกัดจากการใช้งานบนมือถือและวิธีสร้างไฟล์บน GitHub แบบคลิกต่อคลิก
จากการใช้งานจริงของผู้ใช้บนมือถือ Android พบว่า:
1. ไฟล์/โฟลเดอร์ที่ขึ้นต้นด้วยจุด เช่น `.github` และ `.gitkeep` อาจถูกซ่อนหรือไม่แสดงในตัวเลือกไฟล์ของมือถือ และตัวเลือกไฟล์บนมือถือมักไม่รองรับการอัปโหลดทั้งโฟลเดอร์
2. วิธีที่สะดวกที่สุดบนมือถือคือ **สร้างไฟล์ใหม่ตรงๆ บนหน้าเว็บ GitHub** โดยพิมพ์ชื่อไฟล์ที่มี `/` คั่น ระบบจะแยกโฟลเดอร์ให้เอง

**ลำดับการทำแบบคลิกต่อคลิก:**
1. เปิด Repository บน GitHub ในแท็บ **Code**
2. แตะ **Add file** → **Create new file** แล้วสร้างไฟล์ทีละไฟล์ โดยพิมพ์ชื่อไฟล์ในช่องชื่อไฟล์ วางโค้ดในช่องเนื้อหา และกด **Commit changes... → Commit changes** ให้ครบ:
   - `.github/workflows/daily_video.yml`
   - `requirements.txt`
   - `scripts/style.py`
   - `scripts/1_generate_script.py`
   - `scripts/2_generate_voice.py`
   - `scripts/3_generate_images.py`
   - `scripts/4_render_video.py`
   - `scripts/5_save_history.py`
   - `.gitignore`
   - `output/.gitkeep` (ปล่อยว่างแล้วกด Commit changes ได้เลย)
   - `README.md` (หรืออัปโหลดไฟล์ `README.md`)
3. อัปโหลดรูปอ้างอิงเข้าโฟลเดอร์ `assets/` โดยกด **Add file** → **Upload files** แล้วตั้งชื่อเป็น `assets/stickman_ref.png` และ `assets/style_bg_ref.png` แล้วกด **Commit changes**
4. ตั้ง Secrets ทั้ง 4 ตัวที่ **Settings → Secrets and variables → Actions → New repository secret**
5. เปิดสิทธิ์เขียนให้ Actions โดยไปที่ **Settings → Actions → General → Workflow permissions** → เลือก **Read and write permissions** → กด **Save**
6. ไปที่แท็บ **Actions** → เลือก **`daily-video`** → กด **Run workflow** (คง `test_images = true` ไว้ก่อน) รอจนเสร็จ แล้วดาวน์โหลด Artifact มาฟังเสียง `Orus` และตรวจภาพตัวอย่าง 2 ฉาก
7. เมื่อพอใจแล้ว กด **Run workflow** อีกครั้งโดยเอาเครื่องหมายถูก `test_images` ออก (`false`) เพื่อสร้างคลิปเต็ม `output/output.mp4` จากนั้นรอระบบรันอัตโนมัติทุกวันเวลา 08:00 น. (เวลาไทย)

---

## 9. พร้อมท์สำหรับเริ่มต้นในแชทใหม่
```text
สวัสดีครับ ผมต้องการทำงานต่อเกี่ยวกับ "ระบบสร้างคลิปความรู้แปลกๆ อัตโนมัติ (ฟรี 100%)" วันละ 1 คลิป ตามไฟล์สรุปที่แนบมา (ไฟล์สเปกฉบับสมบูรณ์นี้) กรุณาอ่านให้ครบ แล้วยึดการตัดสินใจในหัวข้อ 2 และกติกาในหัวข้อ 3 อย่างเคร่งครัด

สถานะปัจจุบันของผมคือ: [ระบุจุดที่ทำถึงแล้ว เช่น กำลังสร้างไฟล์บน GitHub / รันทดสอบแล้วได้ภาพและเสียงมาตรวจ / ต้องการแก้โค้ดส่วนไหน]

กรุณาช่วยดำเนินการต่อจากจุดนี้ให้ครบถ้วนและชัดเจนครับ
```

---

## 10. บันทึกการตรวจ API ล่าสุด (26 พ.ย. 2026) และข้อที่ยังไม่ยืนยัน
- Gemini TTS: รุ่นปัจจุบันตามเอกสาร Google คือ `gemini-3.1-flash-tts-preview` (มีโควตาฟรี) ส่วน `gemini-2.5-flash-preview-tts` ยังไม่มีประกาศวันปิด ทั้งหมดยังเป็น Preview (ไม่มี SLA รุ่นอาจเปลี่ยนได้)
- Gemini เขียนบท: `gemini-2.5-flash` ยังไม่มีประกาศวันปิดในหน้า deprecations ล่าสุด (มีรุ่นใหม่ เช่น `gemini-3.6-flash`)
- Cloudflare: โควตาฟรี 10,000 Neurons/วัน รีเซ็ต 00:00 UTC; รุ่นที่ถูกจำกัดเฉพาะแผนจ่ายเงินเมื่อ 28 ก.ค. 2026 คือ Kimi K2.6, Kimi K2.7 Code, GLM-5.2 (ไม่รวม FLUX)
- Groq: `openai/gpt-oss-120b` ยังเป็นรุ่นแนะนำ โควตาฟรีประมาณ 30 RPM / 1,000 RPD / 8K TPM จึงจำกัดความยาวคำตอบและตั้ง `reasoning_effort=low`
- Pollinations: endpoint เดิม `image.pollinations.ai/prompt/...` ใช้ได้โดยไม่ต้องมีคีย์ แต่จำกัด ~1 คำขอ/15 วินาทีและอาจมีลายน้ำ
- **ยังไม่ได้ยืนยัน:** จำนวนคำขอ/วันของ Gemini TTS ฟรีสำหรับรุ่น 3.1 และการที่ `stable-diffusion-xl-lightning` ยังอยู่ในแคตตาล็อกฟรีของ Cloudflare — ระบบออกแบบให้ข้ามไปตัวสำรองเองเมื่อใช้ไม่ได้ ดูผลจริงจากการรันโหมดทดสอบ
