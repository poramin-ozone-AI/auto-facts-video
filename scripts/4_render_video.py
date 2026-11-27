"""Render still illustrations with a gentle, centered smoothstep zoom (1.00 -> 1.05)."""
import json
import pathlib
import subprocess
import sys

OUT = pathlib.Path("output")
TMP = OUT / "tmp_clips"
TMP.mkdir(parents=True, exist_ok=True)
FINAL_MP4 = OUT / "output.mp4"
FPS = 30
W, H = 720, 1280

ZOOM_END = 0.05  # ซูมเข้ากลางภาพรวม 5%

def probe_media(path: pathlib.Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True, text=True,
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
    # Smoothstep easing: slow start/end, steady motion in the middle.
    t = f"min(max(on/{max(1, frames-1)},0),1)"
    eased = f"({t})*({t})*(3-2*({t}))"
    zoom = f"1+{ZOOM_END}*{eased}"
    # Always zoom into the exact image center (never leaves the frame, no empty borders).
    x = "iw/2-iw/zoom/2"
    y = "ih/2-ih/zoom/2"
    vf = (
        f"scale={W*2}:{H*2}:flags=lanczos,"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
        "format=yuv420p"
    )
    print(f"  ซูมกลางภาพ 1.00->{1+ZOOM_END:.2f} | {frames} เฟรม")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS),
        "-i", str(img_path), "-i", str(aud_path), "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "1",
        "-t", f"{dur:.3f}", str(clip_path),
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
    for idx, scene in enumerate(scenes):
        clip = TMP / f"clip_{scene['id']:02d}.mp4"
        print(f"เรนเดอร์ฉาก {scene['id']}/{len(scenes)} ({scene['duration']} วิ)...")
        render_scene_clip(scene, idx, clip)
        clip_paths.append(clip)
    concat_list = TMP / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in clip_paths) + "\n", encoding="utf-8")
    print("รวมทุกฉากเป็น output/output.mp4...")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(FINAL_MP4),
    ], check=True)
    if not FINAL_MP4.exists() or FINAL_MP4.stat().st_size < 50_000:
        sys.exit("ไฟล์ output/output.mp4 เล็กผิดปกติหรือสร้างไม่สำเร็จ")
    info = probe_media(FINAL_MP4)
    streams = info.get("streams", [])
    videos = [x for x in streams if x.get("codec_type") == "video"]
    audios = [x for x in streams if x.get("codec_type") == "audio"]
    if not videos or not audios:
        sys.exit(f"ไฟล์วิดีโอขาดสตรีมภาพหรือเสียง (video={len(videos)}, audio={len(audios)})")
    if (int(videos[0]["width"]), int(videos[0]["height"])) != (W, H):
        sys.exit(f"ขนาดวิดีโอสุดท้ายผิด: {videos[0].get('width')}x{videos[0].get('height')}")
    actual = float(info["format"]["duration"])
    expected = float(data["total_duration"])
    if abs(actual - expected) > 0.5:
        sys.exit(f"ความยาววิดีโอเพี้ยน: ได้ {actual:.2f} วิ แต่คาดหวัง {expected:.2f} วิ")
    print(f"OK! สร้าง output/output.mp4 สำเร็จ ({actual:.2f} วิ | {W}x{H})")

if __name__ == "__main__":
    main()
