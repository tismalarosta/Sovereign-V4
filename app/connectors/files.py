"""
File connector — single authority for local file scanning and ingestion.
Scans allowlisted paths only. Surface guard blocks system and project paths.
Phase 5 scope: ~/Documents, ~/Desktop, ~/Downloads, iCloud Drive.
Types: .txt .md .pdf .py .docx .jpg .jpeg .png .mp4 .mov .mp3 .m4a .wav .flac
"""

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.embeddings import embedder
from app.chroma_store import store

DB_PATH = Path(__file__).parent.parent.parent / "data" / "regis.db"
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

ALLOWED_PATHS = [
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs",  # iCloud Drive
]

# Paths that Regis must never read (surface guard)
_BLOCKED_PREFIXES = [
    # System paths
    "/System",
    "/Library",
    "/private/var",
    "/usr",
    "/bin",
    "/sbin",
    str(Path.home() / "Library"),
    # Block own project directory
    str(PROJECT_ROOT),
    # Block all old Sovereign / Regis project versions
    str(Path.home() / "Sovereign V2"),
    str(Path.home() / "Sovereign V1"),
    str(Path.home() / "Sovereign"),
    str(Path.home() / "Regis AI"),
    str(Path.home() / "Regis"),
    # User-specified noisy / irrelevant paths
    str(Path.home() / "Documents/Zoom"),
    str(Path.home() / "Documents/My Games"),
    str(Path.home() / "Documents/GitHub"),
    str(Path.home() / "Documents/Adobe"),
    str(Path.home() / "Documents/Claude"),
    str(Path.home() / "Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents"),
    str(Path.home() / "Library/Mobile Documents/com~apple~Preview/Documents"),
    str(Path.home() / "Library/Mobile Documents/com~apple~TextEdit/Documents"),
    str(Path.home() / "Library/Mobile Documents/iCloud~au~com~savageinteractive~procreate~brushes/Documents"),
]

SUPPORTED_EXTENSIONS = {
    # Text / documents
    ".txt", ".md", ".py", ".pdf", ".docx",
    # Images
    ".jpg", ".jpeg", ".png",
    # Video (metadata only)
    ".mp4", ".mov",
    # Audio (metadata only)
    ".mp3", ".m4a", ".wav", ".flac",
}

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_MEDIA_EXTENSIONS = {".mp4", ".mov", ".mp3", ".m4a", ".wav", ".flac"}

# Size guards — skip files that exceed these limits
TEXT_MAX_BYTES  = 50  * 1024 * 1024   # 50 MB
MEDIA_MAX_BYTES = 500 * 1024 * 1024   # 500 MB

CHUNK_SIZE = 400
CHUNK_OVERLAP = 80

# Optional BLIP image captioning (disabled by default — ~950MB model, slow first run)
CAPTION_IMAGES = False


# ── Surface Guard ─────────────────────────────────────────────────────────────

_BLOCKED_DIR_NAMES = {
    "venv", ".venv", "env", "node_modules", ".git",
    "__pycache__", ".tox", "dist", "build", ".mypy_cache",
}

def _is_allowed(path: Path) -> bool:
    """Return True only if path is safe to read (not a system or project path)."""
    abs_str = str(path.resolve())
    # Block by prefix (old projects, system dirs, noisy user folders)
    for blocked in _BLOCKED_PREFIXES:
        if abs_str.startswith(blocked):
            return False
    # Block by directory name anywhere in the path tree
    for part in path.parts:
        if part in _BLOCKED_DIR_NAMES:
            return False
    return True


# ── Text Extraction ───────────────────────────────────────────────────────────

def _extract_text(path: Path) -> str | None:
    """Extract plain text from a file. Returns None on any failure."""
    try:
        ext = path.suffix.lower()
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _extract_docx(path: Path) -> str | None:
    """Extract paragraph text from a .docx file. Returns None on any failure."""
    try:
        from docx import Document  # python-docx
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        return None


def _extract_image(path: Path) -> str | None:
    """
    Extract EXIF metadata from an image into a searchable text chunk.
    Optionally prepends a BLIP caption if CAPTION_IMAGES is True.
    Returns None on any failure.
    """
    try:
        from PIL import Image, ExifTags
        img = Image.open(str(path))
        width, height = img.size
        file_date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")

        lines = [f"Image: {path.name}", f"Dimensions: {width}×{height}", f"Date: {file_date}"]

        # Extract EXIF if available
        exif_data = img._getexif() if hasattr(img, "_getexif") else None  # type: ignore[attr-defined]
        if exif_data:
            tag_map = {v: k for k, v in ExifTags.TAGS.items()}
            def _get(tag_name: str):
                tag_id = tag_map.get(tag_name)
                return exif_data.get(tag_id) if tag_id else None

            # Camera model
            make = _get("Make")
            model = _get("Model")
            if make or model:
                camera = " ".join(filter(None, [str(make), str(model)])).strip()
                lines.append(f"Camera: {camera}")

            # Original date
            orig_date = _get("DateTimeOriginal")
            if orig_date:
                lines[2] = f"Date: {orig_date}"

            # GPS
            gps_info = _get("GPSInfo")
            if gps_info and isinstance(gps_info, dict):
                try:
                    def _dms_to_dd(dms, ref):
                        d, m, s = dms
                        dd = float(d) + float(m) / 60 + float(s) / 3600
                        if ref in ("S", "W"):
                            dd = -dd
                        return dd
                    lat = _dms_to_dd(gps_info[2], gps_info[1])
                    lon = _dms_to_dd(gps_info[4], gps_info[3])
                    lines.append(f"GPS: {lat:.4f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.4f}°{'E' if lon >= 0 else 'W'}")
                except (KeyError, TypeError, ZeroDivisionError):
                    pass

        # Optional BLIP captioning
        if CAPTION_IMAGES:
            try:
                from transformers import BlipProcessor, BlipForConditionalGeneration  # type: ignore[import]
                import torch
                processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
                model_blip = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
                inputs = processor(img.convert("RGB"), return_tensors="pt")
                with torch.no_grad():
                    out = model_blip.generate(**inputs, max_new_tokens=50)
                caption = processor.decode(out[0], skip_special_tokens=True)
                lines.insert(1, f"Caption: {caption}")
            except Exception:
                pass  # Captioning is optional — skip silently

        return "\n".join(lines)
    except Exception:
        return None


def _extract_media(path: Path) -> str | None:
    """
    Extract metadata from audio/video files via mutagen.
    Returns a single-line searchable text chunk. Returns None on failure.
    """
    try:
        import mutagen
        ext = path.suffix.lower()
        file_name = path.name

        def _fmt_duration(secs: float) -> str:
            mins = int(secs) // 60
            s = int(secs) % 60
            return f"{mins}:{s:02d}"

        meta = mutagen.File(str(path))
        if meta is None:
            return f"Media: {file_name}"

        parts = [f"Media: {file_name}"]

        # Duration
        if hasattr(meta.info, "length"):
            parts.append(f"Duration: {_fmt_duration(meta.info.length)}")

        # Tags — try common tag keys across formats
        def _tag(keys: list[str]) -> str | None:
            for k in keys:
                v = meta.get(k)
                if v:
                    return str(v[0]) if isinstance(v, list) else str(v)
            return None

        title  = _tag(["TIT2", "\xa9nam", "title", "TITLE"])
        artist = _tag(["TPE1", "\xa9ART", "artist", "ARTIST"])
        album  = _tag(["TALB", "\xa9alb", "album", "ALBUM"])
        genre  = _tag(["TCON", "\xa9gen", "genre", "GENRE"])

        if title:  parts.append(f"Title: {title}")
        if artist: parts.append(f"Artist: {artist}")
        if album:  parts.append(f"Album: {album}")
        if genre:  parts.append(f"Genre: {genre}")

        # Bit rate for video
        if ext in (".mp4", ".mov") and hasattr(meta.info, "bitrate"):
            parts.append(f"Bitrate: {meta.info.bitrate // 1000}kbps")

        return " | ".join(parts)
    except Exception:
        return None


# ── Chunking ──────────────────────────────────────────────────────────────────

def _chunk_text(text: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunk = text[start : start + CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


def _chunk_id(abs_path: str, idx: int, text: str) -> str:
    path_hash = hashlib.sha1(abs_path.encode()).hexdigest()[:8]
    text_hash = hashlib.sha1(text.encode()).hexdigest()[:8]
    return f"file::{path_hash}::{idx}::{text_hash}"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _upsert_status(items_indexed: int, status: str) -> None:
    conn = _get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO connectors (name, last_run, items_indexed, status)
        VALUES ('files', ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            last_run=excluded.last_run,
            items_indexed=excluded.items_indexed,
            status=excluded.status
        """,
        (now, items_indexed, status),
    )
    conn.commit()
    conn.close()


# ── Public API ────────────────────────────────────────────────────────────────

def get_status() -> dict:
    """Return current status from the connectors table."""
    conn = _get_db()
    row = conn.execute(
        "SELECT name, last_run, items_indexed, status FROM connectors WHERE name='files'"
    ).fetchone()
    conn.close()
    if row is None:
        return {"connector": "files", "status": "NOT_CONFIGURED", "items_indexed": 0, "last_run": None}
    return dict(row)


def scan(paths: list[Path] | None = None) -> dict:
    """
    Scan allowlisted file paths, chunk, embed, and upsert into ChromaDB.
    Idempotent — re-scans overwrite existing chunks for each file.
    Never raises: errors are captured and returned in the result.
    """
    scan_paths = paths if paths is not None else ALLOWED_PATHS
    files_scanned = 0
    chunks_stored = 0
    errors: list[str] = []

    for base in scan_paths:
        if not base.exists():
            continue
        try:
            file_iter = list(base.rglob("*"))
        except PermissionError:
            errors.append(f"Permission denied: {base}")
            continue

        for fpath in file_iter:
            if not fpath.is_file():
                continue
            ext = fpath.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            if not _is_allowed(fpath):
                continue

            # Size guard
            try:
                file_size = fpath.stat().st_size
            except OSError:
                continue
            max_bytes = MEDIA_MAX_BYTES if ext in _MEDIA_EXTENSIONS else TEXT_MAX_BYTES
            if file_size > max_bytes:
                continue

            # Extract content based on type — images and media produce a single chunk
            if ext in _IMAGE_EXTENSIONS:
                content = _extract_image(fpath)
                single_chunk = True
            elif ext in _MEDIA_EXTENSIONS:
                content = _extract_media(fpath)
                single_chunk = True
            elif ext == ".docx":
                content = _extract_docx(fpath)
                single_chunk = False
            else:
                content = _extract_text(fpath)
                single_chunk = False

            if not content or not content.strip():
                continue

            abs_str = str(fpath.resolve())
            mtime = str(fpath.stat().st_mtime)
            source_key = f"file::{abs_str}"

            chunks = [content] if single_chunk else _chunk_text(content)
            if not chunks:
                continue

            try:
                ids = [_chunk_id(abs_str, i, c) for i, c in enumerate(chunks)]
                embeddings = embedder.embed(chunks)
                metadatas = [
                    {
                        "source": source_key,
                        "source_type": "file",
                        "path": abs_str,
                        "modified": mtime,
                        "chunk_index": i,
                    }
                    for i in range(len(chunks))
                ]
                store.delete_by_source(source_key)
                store.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
                chunks_stored += len(chunks)
                files_scanned += 1
            except Exception as exc:
                errors.append(f"{fpath.name}: {exc}")

    status = "OK" if not errors or files_scanned > 0 else "ERROR"
    _upsert_status(chunks_stored, status)

    return {
        "connector": "files",
        "files_scanned": files_scanned,
        "chunks_stored": chunks_stored,
        "status": status,
        "errors": errors[:5],
    }
