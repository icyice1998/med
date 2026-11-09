"""Convert Apple .pages files to PDF or DOCX using headless LibreOffice."""
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

SOFFICE = os.getenv("SOFFICE_BIN") or shutil.which("soffice") or "soffice"
TIMEOUT = int(os.getenv("CONVERT_TIMEOUT", "180"))

FORMATS = {
    "pdf": ("pdf:writer_pdf_Export", ".pdf"),
    "docx": ('docx:MS Word 2007 XML', ".docx"),
}
PREVIEW_PDF_NAMES = ("QuickLook/Preview.pdf", "preview.pdf")


class ConversionError(Exception):
    pass


def normalize_format(fmt: str) -> str:
    fmt = (fmt or "pdf").strip().lower()
    if fmt in ("word", "doc", "docx"):
        return "docx"
    if fmt == "pdf":
        return "pdf"
    raise ConversionError(f"Unsupported format: {fmt}")


def _unwrap_bundle(src: Path, workdir: Path) -> Path:
    """A .pages 'package' zipped by Finder has one top folder X.pages/; re-zip its contents."""
    try:
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            tops = {n.split("/", 1)[0] for n in names}
            if len(tops) == 1 and next(iter(tops)).endswith(".pages") and any("/" in n for n in names):
                top = next(iter(tops)) + "/"
                fixed = workdir / "unwrapped.pages"
                with zipfile.ZipFile(fixed, "w", zipfile.ZIP_STORED) as out:
                    for n in names:
                        if n.startswith(top) and not n.endswith("/"):
                            out.writestr(n[len(top):], z.read(n))
                return fixed
    except zipfile.BadZipFile:
        raise ConversionError("File is not a valid .pages document (not a zip archive).")
    return src


def _extract_preview_pdf(src: Path, dest: Path) -> bool:
    try:
        with zipfile.ZipFile(src) as z:
            for name in PREVIEW_PDF_NAMES:
                if name in z.namelist():
                    dest.write_bytes(z.read(name))
                    return True
    except zipfile.BadZipFile:
        pass
    return False


def _run_soffice(src: Path, outdir: Path, fmt: str, infilter: str | None = None) -> Path:
    filt, ext = FORMATS[fmt]
    profile = tempfile.mkdtemp(prefix="lo_profile_")
    cmd = [
        SOFFICE, f"-env:UserInstallation=file://{profile}",
        "--headless", "--norestore", "--nolockcheck",
    ]
    if infilter:
        cmd.append(f"--infilter={infilter}")
    cmd += ["--convert-to", filt, "--outdir", str(outdir), str(src)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise ConversionError("Conversion timed out.")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    out = outdir / (src.stem + ext)
    if not out.exists() or out.stat().st_size == 0:
        raise ConversionError("LibreOffice could not read this .pages file.")
    return out


def convert_pages(data: bytes, filename: str, fmt: str = "pdf") -> tuple[bytes, str]:
    """Return (converted_bytes, output_filename)."""
    fmt = normalize_format(fmt)
    stem = Path(filename or "document").stem or "document"
    ext = FORMATS[fmt][1]

    with tempfile.TemporaryDirectory(prefix="pages_") as tmp:
        work = Path(tmp)
        src = work / "input.pages"
        src.write_bytes(data)
        src = _unwrap_bundle(src, work)
        outdir = work / "out"
        outdir.mkdir()

        try:
            out = _run_soffice(src, outdir, fmt)
        except ConversionError:
            # Fallback: older Pages files embed a full PDF preview
            preview = work / "preview.pdf"
            if not _extract_preview_pdf(src, preview):
                raise
            if fmt == "pdf":
                out = preview
            else:
                out = _run_soffice(preview, outdir, "docx", infilter="writer_pdf_import")
        return out.read_bytes(), stem + ext
