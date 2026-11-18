# README visuals

- **cover.svg** — original vector cover with no external resources or scripts.
- **workflow.gif** — an illustrated sequence using synthetic line/circle geometry from the integration workflow. It is **not a live AutoCAD screen recording**.
- **autocad-demo.gif** — real AutoCAD 2026 window snapshots from scripted MCP stdio calls using COM. This is an edited step sequence, with waiting time trimmed and captions added outside the captured window. The Windows taskbar is cropped out. It demonstrates a scratch mounting plate, not a model conversation or HTTP Bridge execution.

The cover and illustrated workflow are original project artwork under the repository's MIT license. The real capture contains AutoCAD UI; Autodesk retains its UI and trademarks. Only test geometry is shown, with no user engineering drawings, recent-file listings, or credentials. The illustrated GIF remains available as a fallback.

Regenerate from the repository root:

~~~powershell
# Pillow is needed only to author documentation assets.
python -m pip install Pillow
python scripts/render_readme_assets.py
~~~

The generator uses Segoe UI/Consolas on Windows and DejaVu fonts elsewhere.
Contact-sheet previews go under .git/readme-preview/ and are not committed.

To package the real capture again, retain its local PNG snapshots, frames.json and events.json, then run:

~~~powershell
python scripts/package_demo_capture.py --input <capture-directory> --source-commit <recorded-commit>
~~~

This packager does not automate AutoCAD or generate CAD pixels. Its crop and captions match the mounting-plate capture layout (1599 x 1000 source pixels). A new recording with a different layout needs an updated crop. Raw snapshots remain local; the published [capture record](../validation/2026-11-18-readme-demo.json) includes source-frame hashes, actual MCP arguments, verified entities and cleanup results.
