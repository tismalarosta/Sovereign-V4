"""
make_app.py — One-time setup script.
Creates ~/Applications/Regis.app: a native macOS .app bundle you can pin to the dock.

Usage:
    cd "/Users/matisselg/Sovereign V3"
    ./venv/bin/python scripts/make_app.py
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
APP_DEST     = Path.home() / "Applications" / "Regis.app"
CONTENTS     = APP_DEST / "Contents"
MACOS_DIR    = CONTENTS / "MacOS"
RES_DIR      = CONTENTS / "Resources"

# ── Info.plist ────────────────────────────────────────────────────────────────

INFO_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>regis</string>
    <key>CFBundleIdentifier</key>
    <string>com.regis.sovereign</string>
    <key>CFBundleName</key>
    <string>Regis</string>
    <key>CFBundleDisplayName</key>
    <string>Regis</string>
    <key>CFBundleIconFile</key>
    <string>regis</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key>
        <true/>
    </dict>
</dict>
</plist>
"""

# ── Launcher shell script ─────────────────────────────────────────────────────

LAUNCHER = f"""\
#!/bin/bash
# Regis launcher — opens the native window; starts server if launchd hasn't.
cd "{PROJECT_ROOT}"
exec ./venv/bin/python run.py
"""

# ── Icon generation ────────────────────────────────────────────────────────────

# Required iconset sizes: (logical, scale) → filename
ICONSET_SIZES = [
    (16,   1, "icon_16x16.png"),
    (16,   2, "icon_16x16@2x.png"),
    (32,   1, "icon_32x32.png"),
    (32,   2, "icon_32x32@2x.png"),
    (128,  1, "icon_128x128.png"),
    (128,  2, "icon_128x128@2x.png"),
    (256,  1, "icon_256x256.png"),
    (256,  2, "icon_256x256@2x.png"),
    (512,  1, "icon_512x512.png"),
    (512,  2, "icon_512x512@2x.png"),
]


def _make_icon_png(size: int):
    """Render the Regis icon at `size`×`size` pixels and return a PIL Image."""
    from PIL import Image, ImageDraw, ImageFont

    bg   = (10, 10, 10, 255)     # #0a0a0a
    green = (0, 255, 136, 255)   # #00ff88

    img  = Image.new("RGBA", (size, size), bg)
    draw = ImageDraw.Draw(img)

    # Rounded rectangle border
    pad    = max(2, size // 20)
    radius = max(4, size // 8)
    stroke = max(1, size // 80)
    draw.rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1],
        radius=radius,
        outline=green,
        width=stroke,
    )

    # Letter "R" — try a decent font, fall back to default
    font_size = int(size * 0.58)
    font = None
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
        "/System/Library/Fonts/Monaco.ttf",
        "/Library/Fonts/SF-Mono-Bold.otf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for fp in font_candidates:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except (IOError, OSError):
            continue

    letter = "R"
    if font:
        bbox = draw.textbbox((0, 0), letter, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (size - tw) / 2 - bbox[0]
        y = (size - th) / 2 - bbox[1] - size * 0.04  # slight upward nudge
        draw.text((x, y), letter, font=font, fill=green)
    else:
        # Fallback: PIL default bitmap font (small but always available)
        draw.text((size // 2, size // 2), letter, fill=green, anchor="mm")

    return img


def build_icns(dest_icns: Path) -> None:
    """Generate regis.icns via iconutil."""
    with tempfile.TemporaryDirectory() as tmp:
        iconset_dir = Path(tmp) / "regis.iconset"
        iconset_dir.mkdir()

        # Render largest first, then resize down for smaller sizes
        master = _make_icon_png(1024)

        for logical, scale, filename in ICONSET_SIZES:
            px = logical * scale
            img = master.resize((px, px), resample=3)  # LANCZOS
            img.save(iconset_dir / filename, format="PNG")
            print(f"  {filename} ({px}×{px})")

        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(dest_icns)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  WARNING: iconutil failed: {result.stderr.strip()}")
            print("  App will work but without a custom icon.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Building Regis.app → {APP_DEST}")

    # Remove existing bundle
    if APP_DEST.exists():
        shutil.rmtree(APP_DEST)
        print("  Removed old bundle.")

    # Create ~/Applications if needed
    APP_DEST.parent.mkdir(parents=True, exist_ok=True)

    # Directory structure
    MACOS_DIR.mkdir(parents=True)
    RES_DIR.mkdir(parents=True)
    print("  Created bundle structure.")

    # Info.plist
    (CONTENTS / "Info.plist").write_text(INFO_PLIST)
    print("  Wrote Info.plist.")

    # Launcher script
    launcher_path = MACOS_DIR / "regis"
    launcher_path.write_text(LAUNCHER)
    launcher_path.chmod(0o755)
    print("  Wrote launcher script (chmod 755).")

    # Icon
    print("  Generating icon…")
    try:
        build_icns(RES_DIR / "regis.icns")
        print("  Icon built.")
    except Exception as exc:
        print(f"  WARNING: icon generation failed ({exc}). App will use default icon.")

    # Remove Gatekeeper quarantine (local app, not downloaded)
    subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(APP_DEST)],
        capture_output=True,
    )

    # Notify Finder so the icon appears immediately
    subprocess.run(
        ["touch", str(APP_DEST)],
        capture_output=True,
    )

    print()
    print("✓ Done!  Regis.app is at:")
    print(f"   {APP_DEST}")
    print()
    print("Next steps:")
    print("  1. Open Finder → go to ~/Applications")
    print("  2. Right-click Regis.app → Open  (first launch only, Gatekeeper)")
    print("  3. Drag Regis.app to your Dock")
    print()
    print("Or open it right now:")
    print(f"   open '{APP_DEST}'")


if __name__ == "__main__":
    main()
