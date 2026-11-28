"""Render still illustrations (static, no zoom) + burned-in Thai subtitles (v4.3).

python scripts/4_render_video.py          เรนเดอร์เต็ม -> output/output.mp4 (+ output/subtitles.srt)
python scripts/4_render_video.py --test   เรนเดอร์ตัวอย่างเฉพาะฉากทดสอบ (จาก output/test_scenes.json) -> output/test_output.mp4
"""
import json
import pathlib
import subprocess
import sys

import subtitles

OUT = pathlib.Path("output")
TMP = OUT / "tmp_clips"
TMP.mkdir(parents=True, exist_ok=True)
FINAL_MP4 = OUT / "output.mp4"
TEST_MP4 = OUT / "test_output.mp4"
SUBS_DIR = OUT / "subs"
SRT_PATH = OUT / "subtitles.srt"
FPS = 30
W, H = 1080, 1920


def probe_media(path: pathlib.Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"ffprobe อ่านไฟล์ไม่ได้: {path} ({r.stderr.strip()})")
    return json.loads(r.stdout)

def render_scene_clip(scene: dict, idx: int, clip_path: pathlib.Path, ass_path: pathlib.Path = None):
    img_path = pathlib.Path(scene["image"])
    aud_path = pathlib.Path(scene["audio"])
    if not img_path.exists():
        sys.exit(f"ไม่พบไฟล์ภาพฉาก {scene['id']}: {img_path}")
    if not aud_path.exists():
        sys.exit(f"ไม่พบไฟล์เสียงฉาก {scene['id']}: {aud_path}")

    dur = float(scene["duration"])
    frames = max(1, int(round(dur * FPS)))
    # v4.3: ภาพนิ่ง ไม่ซูม
    base_vf = f"scale={W}:{H}:flags=lanczos"
    print(f"  ภาพนิ่ง | {frames} เฟรม" + (" | + ซับ" if ass_path else ""))

    def run(vf: str):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS),
            "-i", str(img_path), "-i", str(aud_path), "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "1",
            "-t", f"{dur:.3f}", str(clip_path),
        ]
        subprocess.run(cmd, check=True)

    if ass_path:
        try:
            # ซับเบิร์นหลังซูม (ซับไม่ขยับตามภาพ)
            run(f"{base_vf},ass=filename='{ass_path.as_posix()}',format=yuv420p")
            return
        except subprocess.CalledProcessError as e:
            print(f"WARNING: เบิร์นซับฉาก {scene['id']} ไม่สำเร็จ ({e}) -> เรนเดอร์ฉากนี้โดยไม่มีซับ")
    run(f"{base_vf},format=yuv420p")


def load_test_scenes(data: dict) -> list[dict]:
    """ฉากทดสอบ: id/เสียง/ความยาวจาก output/test_scenes.json (ขั้น 2) + ภาพจาก output/images (ขั้น 3)"""
    ts = OUT / "test_scenes.json"
    if not ts.exists():
        sys.exit("ไม่พบ output/test_scenes.json (ต้องรัน 2_generate_voice.py --test ก่อน)")
    by_id = {int(s["id"]): s for s in data["scenes"]}
    scenes = []
    for e in json.loads(ts.read_text(encoding="utf-8")):
        sc = dict(by_id[int(e["id"])])
        sc["audio"] = e["audio"]
        sc["duration"] = float(e["duration"])
        sc["image"] = str(OUT / "images" / f"scene_{int(e['id']):02d}.png")
        scenes.append(sc)
    return scenes

def main():
    script_path = OUT / "script.json"
    if not script_path.exists():
        sys.exit("ไม่พบ output/script.json")
    data = json.loads(script_path.read_text(encoding="utf-8"))
    test = "--test" in sys.argv
    scenes = load_test_scenes(data) if test else data["scenes"]
    final_mp4 = TEST_MP4 if test else FINAL_MP4
    for f in TMP.glob("*.mp4"):
        f.unlink()
    # ซับ: ล้มเหลวตรงไหนก็เรนเดอร์ต่อโดยไม่มีซับ ไม่ให้ทั้งคลิปล้ม
    ass_paths = {}
    if subtitles.ENABLED:
        try:
            for f in SUBS_DIR.glob("*.ass"):
                f.unlink()
            ass_paths = subtitles.build_subtitles(scenes, SUBS_DIR, SRT_PATH)
        except Exception as e:
            print(f"WARNING: สร้างซับไม่สำเร็จ ({type(e).__name__}: {e}) -> เรนเดอร์โดยไม่มีซับ")
            ass_paths = {}
    else:
        print("ซับปิดอยู่ (SUBTITLES_ENABLED=0)")
    clip_paths = []
    for idx, scene in enumerate(scenes):
        clip = TMP / f"clip_{scene['id']:02d}.mp4"
        print(f"เรนเดอร์ฉาก {scene['id']}/{len(scenes)} ({scene['duration']} วิ)...")
        render_scene_clip(scene, idx, clip, ass_paths.get(int(scene["id"])))
        clip_paths.append(clip)
    concat_list = TMP / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in clip_paths) + "\n", encoding="utf-8")
    print(f"รวมทุกฉากเป็น {final_mp4}...")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k", "-af",
        "loudnorm=I=-14:TP=-1.0:LRA=7:print_format=summary", "-movflags", "+faststart",
        str(final_mp4),
    ], check=True)
    if not final_mp4.exists() or final_mp4.stat().st_size < 50_000:
        sys.exit(f"ไฟล์ {final_mp4} เล็กผิดปกติหรือสร้างไม่สำเร็จ")
    info = probe_media(final_mp4)
    streams = info.get("streams", [])
    videos = [x for x in streams if x.get("codec_type") == "video"]
    audios = [x for x in streams if x.get("codec_type") == "audio"]
    if not videos or not audios:
        sys.exit(f"ไฟล์วิดีโอขาดสตรีมภาพหรือเสียง (video={len(videos)}, audio={len(audios)})")
    if (int(videos[0]["width"]), int(videos[0]["height"])) != (W, H):
        sys.exit(f"ขนาดวิดีโอสุดท้ายผิด: {videos[0].get('width')}x{videos[0].get('height')}")
    actual = float(info["format"]["duration"])
    expected = sum(float(sc["duration"]) for sc in scenes) if test else float(data["total_duration"])
    if abs(actual - expected) > 0.5:
        sys.exit(f"ความยาววิดีโอเพี้ยน: ได้ {actual:.2f} วิ แต่คาดหวัง {expected:.2f} วิ")
    print(f"OK! สร้าง {final_mp4} สำเร็จ ({actual:.2f} วิ | {W}x{H})" + (" [ตัวอย่างทดสอบ]" if test else ""))

if __name__ == "__main__":
    main()
