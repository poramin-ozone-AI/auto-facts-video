"""ขั้น 4: ตัดต่อภาพนิ่ง + ซูมเข้าช้าๆ + รวมเสียงทุกฉาก -> output/output.mp4 (1280x720, 30fps, H.264/AAC)

รายละเอียดตามสเปกข้อ 6.4:
- ขยายภาพต้นฉบับก่อนเข้า zoompan (2560x1440) เพื่อลดอาการสั่น/กระตุกของซับพิกเซล
- ซูมเข้าช้าๆ (1.00 -> 1.13) ตลอด duration จริงของแต่ละฉาก
- สลับจุดโฟกัสการซูมระหว่างฉากไม่ให้ซ้ำซาก (ถ้าเป็นฉาก stickman โฟกัสช่วงกลาง-บนใกล้ตัวละคร)
- ตรวจสอบ output.mp4 ด้วย ffprobe: ต้องมีทั้งภาพและเสียง ขนาด 1280x720 และความยาวคลาดเคลื่อน <= 0.5 วินาที
"""
import json
import pathlib
import subprocess
import sys

OUT = pathlib.Path("output")
TMP = OUT / "tmp_clips"
TMP.mkdir(parents=True, exist_ok=True)
FINAL_MP4 = OUT / "output.mp4"

FPS = 30

STICKMAN_FOCUSES = [
    ("iw/2-(iw/zoom/2)", "ih*0.42-(ih/zoom/2)"),
    ("iw*0.45-(iw/zoom/2)", "ih*0.45-(ih/zoom/2)"),
    ("iw*0.55-(iw/zoom/2)", "ih*0.45-(ih/zoom/2)"),
    ("iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
]

OBJECT_FOCUSES = [
    ("iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    ("iw*0.46-(iw/zoom/2)", "ih*0.46-(ih/zoom/2)"),
    ("iw*0.54-(iw/zoom/2)", "ih*0.54-(ih/zoom/2)"),
    ("iw*0.54-(iw/zoom/2)", "ih*0.46-(ih/zoom/2)"),
]


def probe_media(path: pathlib.Path) -> dict:
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"ffprobe อ่านไฟล์ไม่ได้: {path} ({r.stderr.strip()})")
    return json.loads(r.stdout)


def render_scene_clip(scene: dict, idx: int, clip_path: pathlib.Path):
    img_path = pathlib.Path(scene["image"])
    aud_path = pathlib.Path(scene["audio"])
    if not img_path.exists():
        sys.exit(f"ไม่พบไฟล์ภาพฉาก {scene['id']}: {img_path}")
    if not aud_path.exists():
        sys.exit(f"ไม่พบไฟล์เสียงฉาก {scene['id']}: {aud_path}")

    dur = float(scene["duration"])
    frames = max(1, int(round(dur * FPS)))

    focus_pool = STICKMAN_FOCUSES if scene.get("type") == "stickman" else OBJECT_FOCUSES
    fx, fy = focus_pool[idx % len(focus_pool)]

    zoom_expr = f"min(1.0+0.13*(on/{frames}),1.13)"
    vf = (
        "scale=2560:1440:flags=lanczos,"
        f"zoompan=z='{zoom_expr}':x='{fx}':y='{fy}':d={frames}:s=1280x720:fps={FPS},"
        "format=yuv420p"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-framerate",
        str(FPS),
        "-i",
        str(img_path),
        "-i",
        str(aud_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-ac",
        "1",
        "-t",
        f"{dur:.3f}",
        str(clip_path),
    ]
    subprocess.run(cmd, check=True)


def main():
    script_path = OUT / "script.json"
    if not script_path.exists():
        sys.exit("ไม่พบ output/script.json")

    data = json.loads(script_path.read_text(encoding="utf-8"))
    scenes = data["scenes"]

    for f in TMP.glob("*.mp4"):
        f.unlink()

    clip_paths = []
    for idx, s in enumerate(scenes):
        clip = TMP / f"clip_{s['id']:02d}.mp4"
        print(f"เรนเดอร์ฉาก {s['id']}/{len(scenes)} ({s['duration']} วิ)...")
        render_scene_clip(s, idx, clip)
        clip_paths.append(clip)

    concat_list = TMP / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in clip_paths) + "\n",
        encoding="utf-8",
    )

    print("รวมทุกฉากเป็น output/output.mp4...")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(FINAL_MP4),
        ],
        check=True,
    )

    if not FINAL_MP4.exists() or FINAL_MP4.stat().st_size < 50_000:
        sys.exit("ไฟล์ output/output.mp4 เล็กผิดปกติหรือสร้างไม่สำเร็จ")

    info = probe_media(FINAL_MP4)
    streams = info.get("streams", [])
    v_streams = [st for st in streams if st.get("codec_type") == "video"]
    a_streams = [st for st in streams if st.get("codec_type") == "audio"]

    if not v_streams or not a_streams:
        sys.exit(f"ไฟล์วิดีโอขาดสตรีมภาพหรือเสียง (video={len(v_streams)}, audio={len(a_streams)})")

    vw, vh = int(v_streams[0]["width"]), int(v_streams[0]["height"])
    if (vw, vh) != (1280, 720):
        sys.exit(f"ขนาดวิดีโอสุดท้ายผิด: {vw}x{vh} (ต้องเป็น 1280x720)")

    actual_dur = float(info["format"]["duration"])
    expected_dur = float(data["total_duration"])
    diff = abs(actual_dur - expected_dur)
    if diff > 0.5:
        sys.exit(f"ความยาววิดีโอเพี้ยน: ได้ {actual_dur:.2f} วิ แต่คาดหวัง {expected_dur:.2f} วิ (ต่าง {diff:.2f} วิ)")

    size_mb = FINAL_MP4.stat().st_size / (1024 * 1024)
    print(f"OK! สร้าง output/output.mp4 สำเร็จ ({actual_dur:.2f} วิ | 1280x720 | {size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
