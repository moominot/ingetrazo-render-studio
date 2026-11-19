"""A stand-in for `blender -b --python studio_scene.py -- job.json` in serve mode:
same protocol (INGETRAZO ready / done; {"reload": job} builds another job's scene in the
same process), writes a plain PNG per request. For tests only."""
import json, os, struct, sys, zlib
log = os.environ.get("FAKE_BLENDER_LOG")
def note(text):
    if log:
        with open(log, "a") as f: f.write(text + "\n")
def load(path, how):
    job = json.load(open(path))
    st = job.get("studio") or {}
    note(f"{how} studio={'studio' in job} serve={job.get('serve')} samples={job.get('samples')} "
         f"engine={job.get('engine')} live={st.get('live')} pid={os.getpid()}")
    return job
def png(path, w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d): c = struct.pack(">I", len(d)) + t + d; return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
job = load(sys.argv[-1], "load")
print("INGETRAZO ready", flush=True)
n = 0
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    req = json.loads(line)
    if req.get("quit"): break
    if req.get("reload"):
        job = load(req["reload"], "reload")
        print("INGETRAZO ready", flush=True)
        continue
    n += 1
    png(req["output"], max(1, int(req["width"]) // 8), max(1, int(req["height"]) // 8), (40 + n * 20 % 200, 90, 160))
    note(f"render {n} samples={req.get('samples')} width={req.get('width')}")
    print("INGETRAZO done", req["output"], flush=True)
