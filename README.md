# Auto Facts Video (ระบบสร้างคลิปความรู้แปลกๆ อัตโนมัติ ฟรี 100%)

ระบบสร้างวิดีโอสั้นความรู้แปลกๆ ภาษาไทยความละเอียด **720×1280 (แนวตั้ง 9:16)** ความยาวประมาณ **40–90 วินาที** วันละ 1 คลิปอัตโนมัติบน **GitHub Actions** โดยใช้ API ฟรีทั้งหมด

---

## โครงสร้างโปรเจกต์

```text
auto-facts-video/
├── .github/workflows/daily_video.yml   # Workflow ตั้งเวลา 08:00 น. (เวลาไทย) + กดรันทดสอบได้
├── scripts/
│   ├── style.py                        # ข้อความคุมสไตล์ภาพสีน้ำ + มุมกล้อง + ตัวดึง IDENTITY LOCK (prompt ภาพ = ฉาก -> identity -> มุมกล้อง -> สไตล์ ไม่ส่งบทพากย์เข้าโมเดลภาพ)
│   ├── 0_check_models.py               # ขั้น 0: เตือนถ้าชื่อโมเดล Gemini ที่ตั้งไว้ไม่อยู่ในรายการของ API (ไม่ทำให้ล้ม)
│   ├── 1_generate_script.py            # ขั้น 1: สร้างบท JSON (Gemini หลายรุ่น -> Groq สำรอง; หมุนหมวดหัวข้อตามวัน)
│   ├── 2_generate_voice.py             # ขั้น 2: เสียงพากย์ (Gemini TTS 3.8 -> edge-tts สำรองทั้งคลิป)
│   ├── 3_generate_images.py            # ขั้น 3: ภาพ 9:16 สไตล์สีน้ำ (Cloudflare FLUX.2 klein -> FLUX.1 schnell -> Pollinations)
│   ├── 4_render_video.py               # ขั้น 4: ซูมภาพนิ่งเข้ากลางภาพช้าๆ (1.00→1.05) + เบิร์นซับ + รวมเสียงเป็น output.mp4 (--test = ตัวอย่าง 2 ฉาก)
│   ├── subtitles.py                    # (v3.9) ตัดท่อนซับไทย + คำสำคัญสีเหลือง -> .ass / .srt
│   ├── 5_save_history.py               # ขั้น 5: บันทึกหัวข้อที่ใช้แล้ว (ทำหลังคลิปสำเร็จเท่านั้น)
│   └── compare_flux_models.py          # ทดสอบแยก FLUX.2 klein 4B เทียบ 9B (ไม่กระทบงานผลิต)
├── output/
│   └── topics_history.txt              # สร้างอัตโนมัติ: บันทึกหัวข้อที่ใช้แล้ว (commit กลับ repo)
├── .gitignore
├── requirements.txt
├── README.md
└── PROJECT_SPEC.md                     # สเปกฉบับสมบูรณ์ (อ้างอิงตามโค้ดเป็นหลัก)
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
| `GEMINI_MODEL` | `gemini-3.8-flash` | โมเดลเขียนบทหลัก |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.6-flash,gemini-3.5-flash-lite` | รุ่นสำรองของ Gemini (ลองตามลำดับเมื่อรุ่นหลักใช้ไม่ได้/429) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | โมเดลเขียนบทสำรองบน Groq |
| `GEMINI_TTS_MODEL` | `gemini-3.8-flash-tts` | โมเดลเสียงพากย์หลัก |
| `GEMINI_TTS_FALLBACK_MODELS` | (ว่าง) | รุ่นเสียงสำรอง ปล่อยว่างเพราะ `gemini-3.8-flash-lite-tts` ไม่รองรับภาษาไทย ถ้า 3.8 ใช้ไม่ได้จะไป edge-tts |
| `GEMINI_VOICE` | `Orus` | เสียงพากย์ชาย (ตัวเลือกอื่น: `Charon`, `Algenib`, `Schedar`, `Fenrir`) |
| `GEMINI_TTS_DELAY` | `31` | วินาทีที่เว้นระหว่างฉาก เพื่อไม่ให้เกินโควตาฟรี |
| `EDGE_VOICE` / `VOICE_RATE` / `VOICE_PITCH` | `th-TH-NiwatNeural` / `+0%` / `-2Hz` | เสียงสำรอง edge-tts (v3.7 ปรับ rate จาก `-8%` เป็น `+0%` ให้ใกล้จังหวะ Gemini ที่เร็วขึ้น ปรับได้หลังฟังจริง) |
| `AUDIO_TAIL_PAD` | `0.4` | เว้นความเงียบท้ายเสียงแต่ละฉาก (วินาที) ให้จังหวะไม่รีบ |
| `SCRIPT_MIN_CHARS` / `SCRIPT_MAX_CHARS` | `520` / `1250` | ความยาวบทพากย์รวม (ตัวอักษร) ถ้าคลิปสั้นกว่า 35 วินาทีบ่อย ให้ขยับค่าต่ำสุดขึ้น |
| `VOICE_DIRECTIONS_ENABLED` | ทั้ง 6 แบบ | อารมณ์เสียงรายฉากที่เปิดใช้ (คั่นด้วยจุลภาค) ตัดแบบที่ฟังแล้วไม่ต่างออกได้ `informative` เปิดอยู่เสมอ |
| `IMAGE_DETAIL_LEVEL` | `rich` | (v3.8) ความละเอียดภาพ: `rich` = มีคน/ท่าทาง/ฉากหน้า-กลาง-หลัง/ของประกอบ/แสง, `standard` = ปานกลาง ใช้ถ้าภาพแน่นเกินหรือโมเดลทำตามไม่ครบ |
| `SUBTITLES_ENABLED` / `SUBTITLE_KEYWORDS_ENABLED` | `1` / `1` | (v3.9) เปิด/ปิดซับเบิร์น / คำสำคัญสีเหลือง (ปิดอย่างหลังจะไม่ขอ keywords จาก AI) |
| `SUBTITLE_FONT` / `SUBTITLE_FONT_SIZE` / `SUBTITLE_MAX_CHARS` | `Loma` / `54` / `22` | ฟอนต์ไทย (ติดตั้งจาก `fonts-thai-tlwg`) ขนาด และจำนวนตัวอักษรสูงสุดต่อท่อน (บรรทัดเดียว) |
| `SUBTITLE_MARGIN_BOTTOM` / `SUBTITLE_HIGHLIGHT_COLOR` | `230` / `#FFD93B` | ระยะจากขอบล่าง (~18%) และสีคำสำคัญ |
| `CF_IMAGE_MODEL` | `@cf/black-forest-labs/flux-2-klein-4b` | โมเดลภาพหลัก (สั่งขนาด 720×1280 ตรงๆ) |
| `CF_IMAGE_FALLBACK_MODELS` | `@cf/black-forest-labs/flux-1-schnell` | โมเดลภาพสำรองบน Cloudflare |
| `CF_IMAGE_STEPS` | `6` | จำนวนขั้นวาดภาพของ FLUX.1 schnell (1–8) ไม่มีผลกับ klein |
| `ENABLE_POLLINATIONS` | `1` | ตัวสำรองภาพสุดท้าย (ไม่ต้องใช้คีย์ แต่ช้าและอาจมีลายน้ำ) ตั้งเป็น `0` เพื่อปิด |

---

## 3. วิธีทดสอบและใช้งาน

1. แท็บ **Actions** → **daily-video** → **Run workflow** (คง `test_mode` ติ๊กไว้) จะเขียนบท + สร้างเสียง **2 บท** + สร้างภาพ **2 ฉาก** แล้วดาวน์โหลด Artifact `debug-or-test-…` มาฟังเสียง/ดูภาพ (ข้ามการเรนเดอร์และไม่บันทึกหัวข้อ) ใน log ขั้น 2 จะแสดงอารมณ์ ความยาว และอัตราพูด (ตัวอักษร/วินาที) ของแต่ละบทให้เทียบกัน
2. พอใจแล้ว รันอีกครั้งโดยเอาเครื่องหมายถูก `test_mode` ออก จะได้ Artifact `daily-video-…` (`output.mp4`) หลังจากนั้นระบบรันเองทุกวัน 08:00 น. รันที่ล้มเหลวจะได้ Artifact `debug-or-test-…` สำหรับตรวจและหัวข้อจะไม่ถูกนับว่าใช้แล้ว

หัวข้อจะถูกบันทึกลง `output/topics_history.txt` **เฉพาะเมื่อคลิปสำเร็จ** รันที่ล้มเหลวจึงไม่เสียหัวข้อ

---

## 4. ตารางแก้ปัญหาตาม Log ที่พบบ่อย

| อาการ / ข้อความใน Log | สาเหตุ | วิธีแก้ |
|---|---|---|
| `[gemini:...] ใช้ไม่ได้ ข้ามไปตัวถัดไป -> HTTP 404` | Google เปลี่ยน/ปิดชื่อรุ่นโมเดล | ระบบข้ามไปรุ่นสำรอง/Groq เอง แต่ควรแก้ `GEMINI_MODEL` ใน `daily_video.yml` |
| `ทุกรุ่น Gemini TTS ล้มเหลว ... -> สลับไปสร้างใหม่ทั้งคลิปด้วย edge-tts` | โควตา Gemini TTS เต็ม หรือรุ่นถูกปิด | คลิปยังสำเร็จด้วยเสียง `th-TH-NiwatNeural` (วันถัดไปลอง Gemini ใหม่เอง) |
| `[cloudflare:...] ใช้ไม่ได้ต่อไปในการรันนี้` | โควตา/ความจุ Cloudflare เต็ม (429 ซ้ำหลังรอ 30 วินาที) หรือโทเคนผิด (401/403) | ระบบสลับไปรุ่นสำรองเอง ตรวจ Secrets ถ้าเป็น 401/403 โควตารีเซ็ต 00:00 UTC |
| `WARNING: มีภาพจาก Pollinations` | ภาพบางฉากมาจากตัวสำรองสุดท้าย | เปิดดูภาพก่อนโพสต์ว่ามีลายน้ำ/สไตล์ต่างไหม |
| `สร้างภาพไม่สำเร็จทุกผู้ให้บริการ` | ภาพล้มเหลวทุกตัว | ดู log ว่าแต่ละตัวล้มเพราะอะไร แล้วรันใหม่ |
| `Permission denied to github-actions[bot]` ตอน push | ยังไม่ได้เปิดสิทธิ์เขียนให้ Actions | **Settings → Actions → General** เลือก **Read and write permissions** |


## ทดสอบโมเดลภาพ 4B เทียบ 9B (ไม่กระทบงานผลิต)
ตั้งค่า `CLOUDFLARE_API_TOKEN` และ `CLOUDFLARE_ACCOUNT_ID` แล้วรัน:
```bash
python scripts/compare_flux_models.py --prompt "A watercolor illustration of ..."
```
ผลจะอยู่ใน `output/model_compare/` เท่านั้น ไม่แก้ `output/script.json` และไม่เปลี่ยนโมเดลที่ workflow ใช้
**ข้อควรระวัง:** FLUX.2 klein 9B ใช้ Neurons สูงกว่า 4B มาก ควรตรวจยอด/โควตาก่อนรันทดสอบ


## ความคงที่ของตัวละคร (IDENTITY LOCK)
- ตัว/สัตว์/วัตถุที่ปรากฏซ้ำหลายฉากต้องมีบรรทัดแยกท้าย `image_prompt` รูปแบบ `IDENTITY LOCK: [A European robin (Erithacus rubecula), ...]` คัดลอกคำต่อคำทุกฉาก
- `1_generate_script.py` ตรวจรูปแบบ ความชัดเจนของชื่อชนิด และความเหมือนกันของข้อความ ไม่ผ่านจะขอบทใหม่อัตโนมัติ
- ภาพตัดขวาง/ภาพขยายใกล้ (`cross-section` / `close-up macro`) จะไม่ถูกใส่มุมกล้องจาก `SHOTS` ซ้ำ
- เป็น text-only ไม่รับประกันความเหมือน 100% เพราะไม่ส่งภาพอ้างอิงให้โมเดล
- ข้อจำกัดที่ทราบดูหัวข้อ 10 ใน `PROJECT_SPEC.md`


---

## 5. Voice Enhancement v3.7 (เสียงพากย์)

- บุคลิกเสียง: สนุกแบบพอดี เป็นมิตร มีชีวิตชีวา แต่ยังน่าเชื่อถือ
- อารมณ์แยกตามฉากผ่าน `voice_direction`: `curious`, `informative`, `excited`, `mysterious`, `emphatic`, `warm`
- ความเร็วตั้งเป้ากระฉับกระเฉงขึ้นประมาณ 8–10% จากการอ่านสารคดีแบบเนิบช้า โดยเป็นคำสั่งใน style prompt ไม่ใช่การปรับ rate แบบตัวเลข
- ยังคง Gemini TTS และเสียง `Orus` เป็นค่าเริ่มต้น บท `narration` ที่ส่งเข้า TTS ไม่ถูกเติมคำสั่งสไตล์
- ไฟล์ `script.json` รุ่นเก่าที่ไม่มี `voice_direction` จะใช้ `informative` โดยอัตโนมัติ
- Edge TTS fallback ยังสร้างใหม่ทั้งคลิปด้วยเสียงเดิม (rate ปรับเป็น `+0%`) โดยยังไม่ใช้อารมณ์แยกฉาก
- prompt เขียนบทมีคำแนะนำเบาๆ เรื่องลำดับอารมณ์ (ฉากแรกมักเป็น curious/excited ฉากสุดท้ายมักเป็น warm/emphatic) และ log จะเตือนถ้าทุกฉากได้อารมณ์เดียวกัน
- โหมดทดสอบเสียง `python scripts/2_generate_voice.py --test` สร้างแค่ 2 บท (ฉากแรก + ฉากที่อารมณ์ต่างจากฉากแรกใกล้กลางคลิปที่สุด)

ดูรายละเอียดการเปลี่ยนแปลง ข้อจำกัด และแผนทดสอบในหัวข้อ 11 ของ `PROJECT_SPEC.md`

---

## 6. Phase A v3.8 (ภาพละเอียดขึ้น)

- แก้สาเหตุภาพโล่ง: prompt เขียนบทไม่สั่งให้มีคน/ฉากหน้า-หลัง/ของประกอบ และ `STYLE` มีคำว่า "avoid unnecessary clutter"
- `image_prompt` ใหม่ 60–120 คำ (ระดับ `rich`): ประโยคแรกบอก ใคร ทำอะไร ที่ไหน, ต้องเห็นคนทำตาม narration จริง, แยกชั้นภาพ, ของประกอบ 2–3 อย่าง, แสงบรรยากาศ, ไอเดียเชิงสัญลักษณ์ 1 อย่าง, จุดโฟกัสเดียว, ไม่มีตัวหนังสือ
- IDENTITY LOCK ใช้กับกลุ่มคนได้ (เช่น นักพายไวกิ้ง)
- ปรับระดับด้วย `IMAGE_DETAIL_LEVEL` (`rich`/`standard`) ใน workflow ไม่ต้องแก้โค้ด
- เพิ่มเพดานโทเคนคำตอบของ Gemini (`GEMINI_MAX_OUTPUT_TOKENS`, 16384) กัน JSON ถูกตัด
- ยังไม่ได้ทดสอบกับ API จริง ให้รัน `test_mode` แล้วดูภาพ 2 ฉากและ `script.json` ก่อนรันเต็ม
- รายละเอียดในหัวข้อ 12 ของ `PROJECT_SPEC.md`

---

## 7. Phase B v3.9 (ซับไตเติล)

- ซับเบิร์นลงวิดีโอ **บรรทัดเดียว** ตัวหนาขาว ขอบดำ ไม่มีกล่องพื้น อยู่เหนือขอบล่าง ~18% (เลี่ยงปุ่มแพลตฟอร์ม) **คำสำคัญเป็นสีเหลือง** 1–2 คำต่อฉาก (AI เลือกตอนเขียนบท ต้องตรงกับ narration ตรงตัว ไม่ตรงจะถูกตัดทิ้ง)
- ได้ไฟล์ `subtitles.srt` แยก (ไม่มีสี) ใน artifact ไว้อัปโหลดแยกหรือแก้เอง
- ตัดคำไทยด้วย `pythainlp` เวลาแบ่งตามสัดส่วนตัวอักษรในแต่ละฉาก (ไม่ใช่ timestamp รายคำ จึงอาจเลื่อนจากเสียงเล็กน้อย)
- `test_mode` เรนเดอร์ตัวอย่าง 2 ฉากพร้อมซับเป็น `test_output.mp4` ใน artifact `debug-or-test-…`
- ปิดซับได้ด้วย `SUBTITLES_ENABLED: "0"` ปิดแค่สีเหลืองด้วย `SUBTITLE_KEYWORDS_ENABLED: "0"`
- ยังไม่ได้ทดสอบบน GitHub runner จริง (ฟอนต์/pythainlp/จังหวะซับ) ให้รัน `test_mode` ก่อน
- รายละเอียดในหัวข้อ 13 ของ `PROJECT_SPEC.md`
