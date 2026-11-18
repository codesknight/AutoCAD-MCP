"""Package the mounting-plate demo from real window captures, never synthesize CAD pixels."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ("blank", "new_drawing", "Start in a fresh scratch drawing"),
    ("outline", "create_layer + draw_rectangle", "100 x 60 outline on MCP_OUTLINE"),
    ("bore", "draw_circle", "Center (50, 30) / radius 18"),
    ("bolt1", "draw_circle", "Mounting hole 1 / radius 4"),
    ("bolt2", "draw_circle", "Mounting hole 2 / radius 4"),
    ("bolt3", "draw_circle", "Mounting hole 3 / radius 4"),
    ("bolt4", "draw_circle", "Mounting hole 4 / radius 4"),
    ("notes", "draw_text", "Add the drawing title"),
    ("dimension", "add_dimension", "Read the 100-unit width"),
    ("verified", "query_entities", "8 entities returned and checked"),
]

def font(size, bold=False, mono=False):
    windows = Path("C:/Windows/Fonts") / ("consola.ttf" if mono else "segoeuib.ttf" if bold else "segoeui.ttf")
    fallback = "DejaVuSansMono.ttf" if mono else "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(windows) if windows.exists() else fallback, size)

def package(source, output, report_path, commit):
    manifest = json.loads((source / "frames.json").read_text(encoding="utf-8"))
    events = json.loads((source / "events.json").read_text(encoding="utf-8"))
    assert any(e["kind"] == "verified" and e["entity_count"] == 8 for e in events)
    assert any(e["kind"] == "cleanup" and e["remaining_documents"] == [] and e["quit_requested"] for e in events)
    frames, provenance = [], []
    for index, (label, tool, detail) in enumerate(STEPS):
        row = next(r for r in reversed(manifest) if r["label"] == label)
        raw = source / row["file"]
        with Image.open(raw) as capture:
            assert capture.size == (1599, 1000), "This crop is specific to the verified capture layout"
            # Retain the AutoCAD window through its status bar; exclude the Windows taskbar.
            viewport = capture.convert("RGB").crop((0, 0, 1599, 952))
            viewport = viewport.resize((1200, 714), Image.Resampling.LANCZOS)
        im = Image.new("RGB", (1200, 876), "#091321")
        im.paste(viewport, (0, 82))
        draw = ImageDraw.Draw(im)
        draw.ellipse((24, 18, 33, 27), fill="#67dfb0")
        draw.text((44, 12), "ACTUAL AUTOCAD CAPTURE", font=font(15, bold=True), fill="#67dfb0")
        draw.text((24, 38), "From MCP tools to a mounting plate", font=font(27, bold=True), fill="#edf4ff")
        draw.text((958, 20), "AutoCAD 2026", font=font(18), fill="#edf4ff")
        draw.text((958, 48), "COM / MCP stdio", font=font(15, mono=True), fill="#9aacc6")
        draw.text((24, 807), f"{index + 1:02d} / 10   {tool}", font=font(20, mono=True), fill="#72caff")
        draw.text((660, 810), detail, font=font(17), fill="#edf4ff")
        draw.text((24, 846), "Real window snapshots / pauses trimmed / step captions added", font=font(14), fill="#9aacc6")
        frames.append(im)
        provenance.append(dict(step=label, source_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(), captured_at_unix=row["time"]))
    palette_sheet = Image.new("RGB", (1200, 876 * len(frames)))
    for i, frame in enumerate(frames):
        palette_sheet.paste(frame, (0, 876 * i))
    # Preserve the sparse colored CAD strokes when the larger UI dominates quantization.
    # Every reserved color comes from the captured model space, never a recoloring rule.
    model = frames[-1].crop((263, 232, 900, 720))
    colors = sorted(model.getcolors(model.width * model.height), reverse=True)
    strokes = [rgb for count, rgb in colors if max(rgb)-min(rgb)>40 and max(rgb)>60][:64]
    base = palette_sheet.quantize(colors=192).getpalette()[:192*3]
    values = base + [channel for rgb in strokes for channel in rgb]
    values += [0] * (768-len(values))
    palette = Image.new("P", (1, 1))
    palette.putpalette(values)
    encoded = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    durations = [1200, 1800, 1800, 1100, 1100, 1100, 1500, 1800, 2000, 4000]
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded[0].save(output, save_all=True, append_images=encoded[1:], duration=durations, loop=0, optimize=True, disposal=2)
    frames[-1].save(source / "packaged-final.png")
    sheet = Image.new("RGB", (1200, 876))
    for slot, idx in enumerate((0, 2, 6, 9)):
        sheet.paste(frames[idx].resize((600, 438)), ((slot % 2) * 600, (slot // 2) * 438))
    sheet.save(source / "packaged-contact-sheet.png")
    calls = [dict(tool=e["tool"], arguments=e["arguments"]) for e in events if e["kind"] == "tool_start"]
    results = [e for e in events if e["kind"] == "tool_result"]
    assert len(calls) == len(results) == 13
    entities = json.loads(next(e["result"]["result"] for e in results if e["tool"] == "query_entities"))
    recorded_date = datetime.fromtimestamp(manifest[0]["time"], timezone(timedelta(hours=8))).date().isoformat()
    report = dict(recorded_date=recorded_date, timezone="Asia/Shanghai", source_commit=commit,
        backend="com", transport="mcp_stdio", execution="scripted tool calls",
        capture="real AutoCAD window snapshots, edited step sequence",
        editing=["crop Windows taskbar", "resize", "trim waiting time", "add captions outside captured window"],
        source_frames=len(manifest), gif_steps=len(frames), gif_duration_ms=sum(durations),
        tool_calls=calls, verified_entities=entities,
        cleanup=dict(test_documents_remaining=[], owned_cad_process_closed=True),
        frames=provenance, gif_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Packaged {len(frames)} real capture steps: {output.stat().st_size:,} bytes")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Capture directory with frames.json, events.json and PNGs")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/assets/autocad-demo.gif")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/validation/2026-11-18-readme-demo.json")
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    package(args.input, args.output, args.report, args.source_commit)
