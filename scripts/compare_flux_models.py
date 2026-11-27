"""Optional isolated A/B image test for FLUX.2 klein 4B vs 9B.

Usage:
  export CLOUDFLARE_API_TOKEN=...
  export CLOUDFLARE_ACCOUNT_ID=...
  python scripts/compare_flux_models.py --prompt "same prompt for both models"

Writes only to output/model_compare/; does not edit script.json or affect production defaults.
Note: 9B may consume substantially more Neurons. Run only if you accept the account's usage charge.
"""
import argparse, base64, json, os, pathlib, time
import requests

MODELS = {
    "4b": "@cf/black-forest-labs/flux-2-klein-4b",
    "9b": "@cf/black-forest-labs/flux-2-klein-9b",
}
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--width", type=int, default=720)
    ap.add_argument("--height", type=int, default=1280)
    args = ap.parse_args()
    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account:
        raise SystemExit("ต้องตั้ง CLOUDFLARE_API_TOKEN และ CLOUDFLARE_ACCOUNT_ID")
    out = pathlib.Path("output/model_compare")
    out.mkdir(parents=True, exist_ok=True)
    report = {"prompt": args.prompt, "size": [args.width, args.height], "results": []}
    for label, model in MODELS.items():
        url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
        files = {"prompt": (None, args.prompt), "width": (None, str(args.width)), "height": (None, str(args.height))}
        start = time.time()
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, files=files, timeout=240)
            elapsed = round(time.time() - start, 2)
            item = {"model": model, "http_status": r.status_code, "seconds": elapsed}
            r.raise_for_status()
            ctype = r.headers.get("content-type", "").lower()
            if ctype.startswith("image/"):
                data = r.content
            else:
                payload = r.json()
                result = payload.get("result", payload) if isinstance(payload, dict) else payload
                data = base64.b64decode(result["image"])
            path = out / f"flux_klein_{label}.png"
            path.write_bytes(data)
            item.update({"file": str(path), "bytes": len(data)})
            print(f"{label}: HTTP {r.status_code}, {elapsed}s, {len(data)} bytes -> {path}")
            report["results"].append(item)
        except Exception as e:
            item["error"] = f"{type(e).__name__}: {e}"
            if "r" in locals():
                item["response_excerpt"] = r.text[:500]
            report["results"].append(item)
            print(f"{label}: ERROR {item['error']}")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("เปรียบเทียบเสร็จ: ตรวจภาพสองไฟล์และ report.json ใน output/model_compare/")
if __name__ == "__main__":
    main()
