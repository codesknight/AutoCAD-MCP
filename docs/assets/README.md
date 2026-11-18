# README visuals

- **cover.svg** — original vector cover with no external resources or scripts.
- **workflow.gif** — an illustrated sequence using synthetic line/circle geometry from the integration workflow. It is **not a live AutoCAD screen recording**.
- Both are original project documentation artwork under the repository's MIT license. No Autodesk artwork, engineering drawings, credentials, or user screenshots are embedded.

Regenerate from the repository root:

~~~powershell
# Pillow is needed only to author documentation assets.
python -m pip install Pillow
python scripts/render_readme_assets.py
~~~

The generator uses Segoe UI/Consolas on Windows and DejaVu fonts elsewhere.
Contact-sheet previews go under .git/readme-preview/ and are not committed.
