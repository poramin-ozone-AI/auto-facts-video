"""Final MP4 quality checks; no external API calls."""
import json, pathlib, subprocess, sys
VIDEO=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else "output/output.mp4")
def run(args): return subprocess.run(args,capture_output=True,text=True)
def main():
    if not VIDEO.exists(): sys.exit(f"ไม่พบไฟล์ {VIDEO}")
    r=run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(VIDEO)])
    if r.returncode: sys.exit(r.stderr)
    d=json.loads(r.stdout); vs=[x for x in d.get("streams",[]) if x.get("codec_type")=="video"]; aus=[x for x in d.get("streams",[]) if x.get("codec_type")=="audio"]
    errors=[]; warnings=[]
    if not vs or not aus: errors.append("ขาด video/audio stream")
    else:
        v=vs[0]; a=aus[0]
        if (v.get("width"),v.get("height"))!=(1080,1920): errors.append(f"ความละเอียดผิด: {v.get('width')}x{v.get('height')}")
        if v.get("codec_name")!="h264": warnings.append(f"Video codec={v.get('codec_name')} (คาด h264)")
        rate=v.get("avg_frame_rate", "0/1")
        try:
            num,den=rate.split("/"); fps=float(num)/float(den)
            if abs(fps-30)>0.1: errors.append(f"FPS ผิด: {fps:.3f} (คาด 30)")
        except Exception: warnings.append(f"อ่าน FPS ไม่ได้: {rate}")
        if a.get("codec_name")!="aac": warnings.append(f"Audio codec={a.get('codec_name')} (คาด aac)")
        if a.get("channels",0)>2: warnings.append("เสียงมีมากกว่า 2 channels")
    dur=float(d.get("format",{}).get("duration",0) or 0)
    if dur<=1: errors.append("ระยะเวลาวิดีโอผิดปกติ")
    if errors:
        print("QC FAILED:",*errors,sep="\n- "); sys.exit(1)
    print(f"QC PASS: {VIDEO} | {dur:.2f}s | 1080x1920")
    for x in warnings: print("QC WARNING:",x)
if __name__=="__main__": main()
