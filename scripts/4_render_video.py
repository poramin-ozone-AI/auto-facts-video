"""Render still illustrations (static, no zoom) + burned-in Thai subtitles (v4.4).

python scripts/4_render_video.py          เรนเดอร์เต็ม -> output/output.mp4 (+ output/subtitles.srt)
python scripts/4_render_video.py --test   เรนเดอร์ตัวอย่างเฉพาะฉากทดสอบ (จาก output/test_scenes.json) -> output/test_output.mp4
"""
import json
import pathlib
import re
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

def normalize_audio_two_pass(concat_list: pathlib.Path, output_path: pathlib.Path):
    """วัด Integrated Loudness ก่อน แล้วปรับเสียงแบบ 2-pass ไปที่ -14 LUFS / -1 dBTP"""
    target_i = -14.0
    target_tp = -1.0
    target_lra = 7.0
    measure = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-f", "concat", "-safe", "0",
            "-i", str(concat_list), "-vn", "-af",
            f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json",
            "-f", "null", "-",
        ], capture_output=True, text=True,
    )
    if measure.returncode != 0:
        raise RuntimeError(f"วัดระดับเสียงก่อน Normalize ไม่สำเร็จ: {measure.stderr[-1200:]}")
    match = re.search(r"\{\s*\"input_i\".*?\}", measure.stderr, re.S)
    if not match:
        raise RuntimeError("FFmpeg ไม่ส่งค่าที่จำเป็นสำหรับ Loudness Normalization แบบ 2-pass")
    stats = json.loads(match.group(0))
    required = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    if any(k not in stats or stats[k] in ("-inf", "inf", "nan") for k in required):
        raise RuntimeError(f"ค่าที่วัดได้ไม่สมบูรณ์สำหรับ Normalize: {stats}")
    filt = (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:"
        f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:linear=true:print_format=summary"
    )
    print(f"ปรับความดังเสียงแบบ 2-pass: เป้าหมาย {target_i:.0f} LUFS / {target_tp:.0f} dBTP")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-af", filt, "-movflags", "+faststart", str(output_path),
    ], check=True)


def validate_subtitle_paths(scenes: list[dict], ass_paths: dict[int, pathlib.Path]) -> None:
    """ซับต้องมีไฟล์ครบทุกฉาก มิฉะนั้นให้ fallback ทั้งคลิปเป็นไม่มีซับ"""
    expected_ids = {int(scene["id"]) for scene in scenes}
    actual_ids = {int(scene_id) for scene_id in ass_paths}
    if actual_ids != expected_ids:
        raise RuntimeError(
            f"ไฟล์ซับไม่ครบทุกฉาก (มี {sorted(actual_ids)} แต่ต้องมี {sorted(expected_ids)})"
        )


def render_scene_clip(scene: dict, idx: int, clip_path: pathlib.Path, ass_path: pathlib.Path = None):
    img_path = pathlib.Path(scene["image"])
    aud_path = pathlib.Path(scene["audio"])
    if not img_path.exists():
        sys.exit(f"ไม่พบไฟล์ภาพฉาก {scene['id']}: {img_path}")
    if not aud_path.exists():
        sys.exit(f"ไม่พบไฟล์เสียงฉาก {scene['id']}: {aud_path}")

    dur = float(scene["duration"])
    frames = max(1, int(round(dur * FPS)))
    # ภาพนิ่ง ไม่ซูม (v4.3 เป็นต้นไป)
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
            # เบิร์นซับลงบนภาพนิ่ง (ซับอยู่กับที่)
            run(f"{base_vf},ass=filename='{ass_path.as_posix()}',format=yuv420p")
            return
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"เบิร์นซับฉาก {scene['id']} ไม่สำเร็จ") from e
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
    # ซับเป็น all-or-nothing: ถ้าสร้างหรือเบิร์นซับส่วนใดไม่สำเร็จ ให้เรนเดอร์ทั้งคลิปใหม่โดยไม่มีซับ
    ass_paths = {}
    def clear_subtitle_outputs() -> None:
        for f in SUBS_DIR.glob("*.ass"):
            f.unlink(missing_ok=True)
        SRT_PATH.unlink(missing_ok=True)

    if subtitles.ENABLED:
        try:
            clear_subtitle_outputs()
            ass_paths = subtitles.build_subtitles(scenes, SUBS_DIR, SRT_PATH)
            validate_subtitle_paths(scenes, ass_paths)
        except Exception as e:
            print(f"WARNING: สร้างซับไม่สำเร็จ ({type(e).__name__}: {e}) -> เรนเดอร์ทั้งคลิปโดยไม่มีซับ")
            ass_paths = {}
            clear_subtitle_outputs()
    else:
        clear_subtitle_outputs()
        print("ซับปิดอยู่ (SUBTITLES_ENABLED=0)")
    clip_paths = [TMP / f"clip_{scene['id']:02d}.mp4" for scene in scenes]

    def render_all(use_subtitles: bool) -> None:
        for clip in clip_paths:
            clip.unlink(missing_ok=True)
        for idx, (scene, clip) in enumerate(zip(scenes, clip_paths), 1):
            print(f"เรนเดอร์ฉาก {scene['id']}/{len(scenes)} ({scene['duration']} วิ)...")
            render_scene_clip(
                scene, idx - 1, clip,
                ass_paths.get(int(scene["id"])) if use_subtitles else None,
            )

    if ass_paths:
        try:
            render_all(use_subtitles=True)
        except RuntimeError as e:
            print(f"WARNING: {e} -> ยกเลิกซับทั้งคลิปและเรนเดอร์ใหม่ทุกฉากโดยไม่มีซับ")
            ass_paths = {}
            clear_subtitle_outputs()
            render_all(use_subtitles=False)
    else:
        render_all(use_subtitles=False)
    concat_list = TMP / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in clip_paths) + "\n", encoding="utf-8")
    print(f"รวมทุกฉากเป็น {final_mp4}...")
    normalize_audio_two_pass(concat_list, final_mp4)
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
