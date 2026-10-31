"""OCR Windows tramite winrt (OcrEngine). Facoltativo: se manca, errore chiaro."""

from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image


def _raise_missing(exc: Exception) -> RuntimeError:
    return RuntimeError(
        "OCR non disponibile: installa i pacchetti winrt (winrt-Windows.Media.Ocr, "
        "winrt-Windows.Graphics.Imaging, winrt-Windows.Storage.Streams) oppure usa "
        "rapidocr-onnxruntime come fallback. Dettaglio: " + str(exc)
    )


def ocr_image(path: str) -> str:
    """Estrae testo da un'immagine. Solleva RuntimeError se non disponibile."""
    try:
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter
    except Exception as exc:  # pragma: no cover - import opzionale
        raise _raise_missing(exc)

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError(
            "Motore OCR non disponibile: aggiungi un pacchetto lingua con OCR in "
            "Windows (Impostazioni > Ora e lingua > Lingua) oppure installa "
            "rapidocr-onnxruntime."
        )

    try:
        image = Image.open(path).convert("RGBA")
    except Exception as exc:
        raise RuntimeError(f"Impossibile aprire l'immagine {path}: {exc}")

    bgra = image.tobytes("raw", "BGRA")
    writer = DataWriter()
    writer.write_bytes(bgra)
    buffer = writer.detach_buffer()

    bitmap = SoftwareBitmap(BitmapPixelFormat.BGRA8, image.width, image.height)
    bitmap.copy_from_buffer(buffer)

    async def _run():
        result = await engine.recognize_async(bitmap)
        lines = []
        for line in result.lines:
            words = [w.text for w in line.words]
            lines.append(" ".join(words))
        return "\n".join(lines).strip()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        raise RuntimeError(f"OCR fallito: {exc}")
