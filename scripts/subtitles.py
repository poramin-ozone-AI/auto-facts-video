"""ซับไตเติลไทย (v3.9): ซอย narration เป็นท่อนสั้นบรรทัดเดียว + ไฮไลต์คำสำคัญสีเหลือง -> .ass (เบิร์นลงวิดีโอ) และ .srt (แยก)

หลักการ
  - TTS ไม่ให้ timestamp ระดับคำ: ถ้ามี faster-whisper จะใช้เวลา word/segment จากไฟล์เสียงมากำหนดจังหวะท่อนซับ (ข้อความยังเป็น narration ต้นฉบับ)
    ถ้าใช้ Whisper ไม่ได้ จึงแบ่งเวลาของแต่ละฉากตามสัดส่วนจำนวนตัวอักษรของแต่ละท่อน
    (ความคลาดเคลื่อนไม่สะสมข้ามฉาก เพราะเวลาเริ่ม/ยาวของฉากมาจากไฟล์เสียงจริง)
  - ตัดคำไทยด้วย pythainlp (newmm) ถ้าไม่มี/ใช้ไม่ได้ จะตัดที่ช่องว่าง/เครื่องหมายวรรคตอนเท่านั้น และบังคับตัดตามความยาวแบบไม่รู้ขอบคำ (พิมพ์ WARNING)
  - คำสำคัญ (scene["keywords"]) ถูกถือเป็นก้อนเดียว ไม่ถูกตัดขาดกลางคำ

ตัวแปร env (ตั้งใน .github/workflows/daily_video.yml):
  SUBTITLES_ENABLED (1)          เปิด/ปิดซับทั้งหมด
  SUBTITLE_KEYWORDS_ENABLED (1)  เปิด/ปิดสีเหลืองคำสำคัญ (ปิด = ไม่ขอ keywords จาก AI ด้วย)
  SUBTITLE_FONT (Loma)           ชื่อฟอนต์ไทยที่ติดตั้งในเครื่อง (workflow ติดตั้ง fonts-thai-tlwg)
  SUBTITLE_FONT_SIZE (96)        ขนาดตัวอักษร (หน่วยพิกเซลบนวิดีโอ 1080x1920)
  SUBTITLE_MAX_CHARS (22)        จำนวนตัวอักษรสูงสุดต่อท่อน (บรรทัดเดียว)
  SUBTITLE_MARGIN_BOTTOM (345)   ระยะจากขอบล่าง (พิกเซล; 345 ~ 18% ของความสูง 1920 เลี่ยงปุ่ม Shorts/TikTok)
  SUBTITLE_MARGIN_SIDE (90)      ระยะขอบซ้าย/ขวา
  SUBTITLE_OUTLINE (5)           ความหนาขอบดำ
  SUBTITLE_HIGHLIGHT_COLOR (#FFD93B)  สีคำสำคัญ (hex RRGGBB)
"""
import math
import os
import pathlib
import re
import subprocess
import unicodedata

W, H = 1080, 1920

ENABLED = os.getenv("SUBTITLES_ENABLED", "1") != "0"
KEYWORDS_ENABLED = ENABLED and os.getenv("SUBTITLE_KEYWORDS_ENABLED", "1") != "0"
FONT = os.getenv("SUBTITLE_FONT", "Loma")
FONT_SIZE = int(os.getenv("SUBTITLE_FONT_SIZE", "96"))
MAX_CHARS = max(8, int(os.getenv("SUBTITLE_MAX_CHARS", "22")))
MARGIN_BOTTOM = int(os.getenv("SUBTITLE_MARGIN_BOTTOM", "345"))
MARGIN_SIDE = int(os.getenv("SUBTITLE_MARGIN_SIDE", "90"))
OUTLINE = int(os.getenv("SUBTITLE_OUTLINE", "5"))
HIGHLIGHT_COLOR = os.getenv("SUBTITLE_HIGHLIGHT_COLOR", "#FFD93B")
TAIL_PAD = float(os.getenv("AUDIO_TAIL_PAD", "0.2"))  # ความเงียบท้ายเสียงแต่ละฉาก (ต้องตรงกับขั้น 2)

# คำเชื่อม: ถ้าตัดได้ใกล้เคียงกัน ให้ตัดก่อนคำเหล่านี้ (ท่อนใหม่ขึ้นต้นด้วยคำเชื่อมอ่านลื่นกว่า)
CONJUNCTIONS = {"และ", "แต่", "เพราะ", "ที่", "ซึ่ง", "เมื่อ", "หรือ", "จึง", "ก็", "แล้ว", "โดย", "จน", "ขณะที่", "ถ้า", "หาก"}
# ห้ามขึ้นต้นท่อนใหม่ด้วยตัวเหล่านี้
NO_LEADING = ("ๆ", "ฯ", ".", ",", ")", "”", "\"", "?", "!", "…")
PUNCT_EDGE = " \t\r\n,.;:…\"“”'()"

_TOKENIZER = None


def thai_tokens(text: str) -> list[str]:
    """ตัดคำไทย (ต่อกันแล้วต้องได้ข้อความเดิมเป๊ะ) ถ้าใช้ pythainlp ไม่ได้ คืนทีละตัวอักษร (ตัดได้หยาบ)"""
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            from pythainlp.tokenize import word_tokenize

            _TOKENIZER = lambda t: word_tokenize(t, engine="newmm", keep_whitespace=True)  # noqa: E731
        except Exception as e:  # ไม่มีไลบรารี/โหลดไม่ได้
            print(f"WARNING: ใช้ pythainlp ไม่ได้ ({type(e).__name__}: {e}) -> ซับอาจตัดขาดกลางคำ")
            _TOKENIZER = False
    if _TOKENIZER:
        try:
            toks = _TOKENIZER(text)
            if toks and "".join(toks) == text:
                return list(toks)
        except Exception as e:
            print(f"WARNING: ตัดคำไม่สำเร็จ ({type(e).__name__}: {e}) -> ใช้การตัดแบบหยาบสำหรับข้อความนี้")
    return list(text)


def bad_break(prev: str, nxt: str) -> bool:
    """ห้ามตัดระหว่างสองก้อนนี้: ท่อนใหม่ห้ามขึ้นต้นด้วยสระ/วรรณยุกต์ที่ต้องตามพยัญชนะ และท่อนเก่าห้ามจบด้วยสระหน้า (เ แ โ ใ ไ)
    (pythainlp ตัดที่ขอบคำอยู่แล้ว กฎนี้กันกรณีใช้ตัวตัดหยาบสำรอง)"""
    if not prev or not nxt:
        return False
    return nxt.startswith(NO_LEADING) or unicodedata.category(nxt[0]) == "Mn" or nxt[0] in "ะาำ" or prev[-1] in "เแโใไ"


def keyword_spans(text: str, keywords: list[str]) -> list[tuple[int, int]]:
    spans = []
    for k in keywords:
        if not k:
            continue
        for m in re.finditer(re.escape(k), text):
            spans.append((m.start(), m.end()))
    return spans


def _inside(pos: int, spans) -> bool:
    return any(s < pos < e for s, e in spans)


def split_segments(text: str, spans) -> list[str]:
    """แบ่งเป็นวรรคที่ช่องว่าง/เครื่องหมายวรรคตอน (ไม่ตัดกลางคำสำคัญ)"""
    bounds, last = [], 0
    for m in re.finditer(r"[,;:!?…]+\s*|\s+", text):
        if _inside(m.start(), spans) or m.end() >= len(text):
            continue
        bounds.append(m.end())
    segs = []
    for b in bounds + [len(text)]:
        seg = text[last:b]
        if seg.strip(PUNCT_EDGE):
            segs.append(seg)
        last = b
    return segs


def atoms_of(seg: str, seg_start: int, spans) -> list[str]:
    """แตกวรรคเป็นก้อนที่ตัดได้ (คำจาก pythainlp) โดยคำสำคัญรวมเป็นก้อนเดียว"""
    atoms, cur, pos = [], "", seg_start
    for tok in thai_tokens(seg):
        cur += tok
        pos += len(tok)
        if not _inside(pos, spans):
            atoms.append(cur)
            cur = ""
    if cur:
        atoms.append(cur)
    return atoms


def pack(atoms: list[str], max_chars: int) -> list[str]:
    """รวมก้อนเป็นท่อนไม่เกิน max_chars โดยกระจายความยาวให้สมดุล และชอบตัดก่อนคำเชื่อม"""
    chunks, i = [], 0
    while i < len(atoms):
        remaining = sum(len(a) for a in atoms[i:])
        if len("".join(atoms[i:]).strip(PUNCT_EDGE)) <= max_chars:
            chunks.append("".join(atoms[i:]))
            break
        k = math.ceil(remaining / max_chars)
        ideal = remaining / k
        best, acc = None, 0
        for j in range(i, len(atoms) - 1):
            acc += len(atoms[j])
            if len("".join(atoms[i:j + 1]).strip(PUNCT_EDGE)) > max_chars:
                break
            nxt = atoms[j + 1]
            if bad_break(atoms[j], nxt):
                continue
            score = abs(acc - ideal) - (3 if nxt.strip() in CONJUNCTIONS else 0)
            if best is None or score < best[0]:
                best = (score, j)
        if best is None:
            # ก้อนแรกยาวเกิน (ไม่มีจุดตัดที่พอดี) -> ตัดตามจำนวนตัวอักษร
            head = atoms[i]
            if len(head) > max_chars:
                chunks.append(head[:max_chars])
                atoms[i] = head[max_chars:]
            else:
                chunks.append(head)
                i += 1
            continue
        chunks.append("".join(atoms[i:best[1] + 1]))
        i = best[1] + 1
    return chunks


def make_chunks(narration: str, keywords: list[str] | None = None, max_chars: int = None) -> list[tuple[str, bool]]:
    """คืนรายการ (ข้อความท่อน, จบวรรค?) ตามลำดับ"""
    max_chars = max_chars or MAX_CHARS
    text = re.sub(r"[ \t\r\n]+", " ", str(narration)).strip()
    spans = keyword_spans(text, keywords or [])
    out, pos = [], 0
    segs = split_segments(text, spans)
    for si, seg in enumerate(segs):
        start = text.find(seg, pos)
        pos = start + len(seg)
        local_spans = [(s - start, e - start) for s, e in spans if s >= start and e <= start + len(seg)]
        pieces = pack(atoms_of(seg, 0, local_spans), max_chars)
        for pi, piece in enumerate(pieces):
            t = piece.strip(PUNCT_EDGE)
            if t:
                out.append((t, pi == len(pieces) - 1))
    return out


def proportional_scene_cues(scene: dict, duration: float = None) -> list[tuple[float, float, str]]:
    """คืน [(เริ่ม, จบ, ข้อความ)] เวลาอิงจุดเริ่มของคลิปฉากนั้น"""
    duration = float(duration if duration is not None else scene["duration"])
    kws = [k for k in (scene.get("keywords") or []) if isinstance(k, str)] if KEYWORDS_ENABLED else []
    chunks = make_chunks(scene.get("narration", ""), kws)
    if not chunks:
        return []
    speech = max(0.6, duration - TAIL_PAD)
    # น้ำหนักเวลา = จำนวนตัวอักษรไม่รวมช่องว่าง + หน่วงเล็กน้อยเมื่อจบวรรค
    weights = [len(re.sub(r"\s", "", t)) + (2 if end else 0) for t, end in chunks]
    total_w = float(sum(weights)) or 1.0
    cues, t = [], 0.0
    for (text, _), w in zip(chunks, weights):
        d = speech * w / total_w
        cues.append([t, t + d, text])
        t += d
    cues[-1][1] = min(duration, speech + 0.3)
    return [(a, b, c) for a, b, c in cues]


_WHISPER_MODEL = None
_WHISPER_FAILED = False

def scene_cues(scene: dict, duration: float = None) -> list[tuple[float, float, str]]:
    """ใช้เวลา segment จาก faster-whisper แล้วกระจายข้อความต้นฉบับลงในช่วงเสียง; fallback เป็นสัดส่วนเดิมเมื่อโมเดลใช้ไม่ได้"""
    global _WHISPER_MODEL, _WHISPER_FAILED
    duration = float(duration if duration is not None else scene["duration"])
    fallback = proportional_scene_cues(scene, duration)
    audio = scene.get("audio")
    if not audio or not pathlib.Path(audio).exists() or _WHISPER_FAILED:
        return fallback
    try:
        if _WHISPER_MODEL is None:
            from faster_whisper import WhisperModel
            model_name = os.getenv("WHISPER_MODEL", "tiny")
            _WHISPER_MODEL = WhisperModel(model_name, device="cpu", compute_type="int8")
            print(f"โหลด faster-whisper {model_name} (CPU int8)")
        segments, _ = _WHISPER_MODEL.transcribe(str(audio), language="th", word_timestamps=True, vad_filter=True)
        segments = list(segments)
        word_spans = []
        segment_spans = []
        for segment in segments:
            sa, sb = float(segment.start), float(segment.end)
            if sb > sa and str(segment.text).strip():
                segment_spans.append((max(0.0,sa), min(duration,sb), str(segment.text).strip()))
            for word in (getattr(segment, "words", None) or []):
                wa, wb = float(word.start or 0.0), float(word.end or 0.0)
                wt = str(word.word or "").strip()
                if wt and wb > wa:
                    word_spans.append((max(0.0,wa), min(duration,wb), wt))
        # Prefer word timestamps when the model returns them; otherwise use segment timestamps.
        spans = [(a,b,t) for a,b,t in (word_spans or segment_spans) if t and b>a]
        if not spans:
            return fallback
        # Map cumulative character positions in the original narration onto Whisper segment intervals.
        # This preserves the exact original Thai wording while using ASR-derived timing boundaries.
        chunks = make_chunks(scene.get("narration", ""), [k for k in (scene.get("keywords") or []) if isinstance(k, str)] if KEYWORDS_ENABLED else [])
        if not chunks:
            return []
        weights = [max(1, len(re.sub(r"\s", "", t))) for _,_,t in spans]
        total_asr = float(sum(weights))
        total_src = float(sum(max(1, len(re.sub(r"\s", "", t))) for t,_ in chunks))
        def time_at(progress: float) -> float:
            target = min(total_asr, max(0.0, progress * total_asr))
            acc = 0.0
            for (a,b,_), weight in zip(spans, weights):
                if target <= acc + weight:
                    frac = min(1.0, max(0.0, (target-acc)/weight))
                    return a + (b-a)*frac
                acc += weight
            return spans[-1][1]
        out=[]; cursor=0.0
        for text, _ in chunks:
            weight=max(1,len(re.sub(r"\s", "", text)))
            start=time_at(cursor/total_src)
            cursor += weight
            end=time_at(cursor/total_src)
            if end-start < 0.08:
                end=min(duration,start+0.18)
            if end>start:
                out.append((max(0.0,start),min(duration,end),text))
        if not out:
            return fallback
        return out
    except Exception as e:
        _WHISPER_FAILED = True
        print(f"WARNING: faster-whisper ใช้ไม่ได้ ({type(e).__name__}: {e}) -> ใช้ timing แบบเดิม")
        return fallback


# ---------- เขียนไฟล์ ----------

def _ass_color(hex_rgb: str) -> str:
    h = hex_rgb.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        print(f"WARNING: SUBTITLE_HIGHLIGHT_COLOR '{hex_rgb}' ไม่ถูกต้อง -> ใช้ #FFD93B")
        h = "FFD93B"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{b}{g}{r}&".upper()


def _ass_time(sec: float) -> str:
    cs = int(round(sec * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"


def _ass_escape(t: str) -> str:
    return t.replace("\\", "").replace("{", "(").replace("}", ")")


def highlight_ass(text: str, keywords: list[str]) -> str:
    text_e = _ass_escape(text)
    kws = sorted({_ass_escape(k) for k in keywords if k}, key=len, reverse=True)
    if not kws:
        return text_e
    col = _ass_color(HIGHLIGHT_COLOR)
    pat = "(" + "|".join(re.escape(k) for k in kws) + ")"
    parts = re.split(pat, text_e)
    out = []
    for i, p in enumerate(parts):
        if not p:
            continue
        out.append("{\\1c" + col + "}" + p + "{\\1c&HFFFFFF&}" if i % 2 == 1 else p)
    return "".join(out)


def write_ass(cues, keywords: list[str], path: pathlib.Path):
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Default,{FONT},{FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H000A0A0A,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"{OUTLINE},2,2,{MARGIN_SIDE},{MARGIN_SIDE},{MARGIN_BOTTOM},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,{highlight_ass(t, keywords)}"
        for a, b, t in cues
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def write_srt(all_cues, path: pathlib.Path):
    """all_cues: [(เริ่ม, จบ, ข้อความ)] เวลาสะสมทั้งคลิป (ไม่มีสี)"""
    blocks = [f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{t}\n" for i, (a, b, t) in enumerate(all_cues, 1)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(blocks), encoding="utf-8")


def check_font() -> bool:
    """ตรวจว่า fontconfig เจอฟอนต์ที่ตั้งไว้ (ถ้าไม่เจอ libass จะสลับเป็นฟอนต์อื่นซึ่งอาจไม่มีอักษรไทย)"""
    try:
        r = subprocess.run(["fc-match", f"{FONT}:bold", "family", "file"], capture_output=True, text=True, timeout=20)
        print(f"ฟอนต์ซับ: ต้องการ '{FONT}' -> fontconfig เลือก: {r.stdout.strip()}")
        return FONT.lower() in r.stdout.lower()
    except Exception as e:
        print(f"WARNING: ตรวจฟอนต์ซับไม่ได้ ({e})")
        return False


def build_subtitles(scenes: list[dict], ass_dir: pathlib.Path, srt_path: pathlib.Path) -> dict[int, pathlib.Path]:
    """สร้าง .ass รายฉาก (คืน {id ฉาก: path}) และ .srt รวมทั้งคลิป"""
    if not check_font():
        print("WARNING: ไม่พบฟอนต์ซับตามที่ตั้งไว้ (ซับอาจเป็นกล่องสี่เหลี่ยม) ตรวจการติดตั้ง fonts-thai-tlwg ใน workflow")
    ass_paths, all_cues, offset = {}, [], 0.0
    for s in scenes:
        dur = float(s["duration"])
        cues = scene_cues(s, dur)
        if cues:
            p = ass_dir / f"scene_{int(s['id']):02d}.ass"
            write_ass(cues, [k for k in (s.get("keywords") or []) if KEYWORDS_ENABLED], p)
            ass_paths[int(s["id"])] = p
            all_cues.extend((offset + a, offset + b, t) for a, b, t in cues)
            print(f"  ซับฉาก {s['id']}: {len(cues)} ท่อน | " + " | ".join(t for _, _, t in cues))
        offset += dur
    if all_cues:
        write_srt(all_cues, srt_path)
        print(f"สร้างซับ {len(all_cues)} ท่อน -> {srt_path}")
    return ass_paths
