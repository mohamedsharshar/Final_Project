from fastapi import FastAPI, File, UploadFile, HTTPException, Header, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any
from io import BytesIO
from PIL import Image
import uvicorn
import os
import numpy as np
import tempfile
import cv2

# PDF support
try:
    from pdf2image import convert_from_bytes
    PDF_AVAILABLE = True
except Exception:
    PDF_AVAILABLE = False

# Optional API key
API_KEY_ENV = os.getenv("API_KEY")

def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if API_KEY_ENV:
        if not x_api_key or x_api_key != API_KEY_ENV:
            raise HTTPException(status_code=401, detail="Unauthorized: invalid API key")
    return True

# PaddleX models (detection + recognition) matching your notebook
PADDLE_DET_MODEL = os.getenv("PADDLE_DET_MODEL", "PP-OCRv5_server_det")
PADDLE_REC_MODEL = os.getenv("PADDLE_REC_MODEL", "arabic_PP-OCRv5_mobile_rec")

# Lazily initialized models
paddle_detector = None
paddle_recognizer = None

# Try importing paddlex only when needed to avoid import errors on cold envs
paddlex_import_error: Optional[str] = None
try:
    from paddlex import create_model  # type: ignore
except Exception as e:  # noqa: BLE001
    paddlex_import_error = str(e)
    create_model = None  # type: ignore

app = FastAPI(title="OCR Scan Vision API", version="3.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    init_paddle_models()


def init_paddle_models():
    """Initialize PaddleX detector and recognizer once."""
    global paddle_detector, paddle_recognizer
    if create_model is None:
        # paddlex not available yet; endpoints will error with a clear message until deps are installed
        return
    if paddle_detector is None:
        paddle_detector = create_model(PADDLE_DET_MODEL)
    if paddle_recognizer is None:
        paddle_recognizer = create_model(PADDLE_REC_MODEL)


@app.get("/")
async def root():
    backend = "paddlex" if create_model else "unavailable"
    return {"name": "OCR Scan Vision API", "status": "ok", "ocr_backend": backend}


@app.get("/health")
async def health():
    return {"status": "healthy"}


# ------------- Helper functions (Notebook-faithful pipeline) ------------- #

def _pil_to_bgr(img: Image.Image) -> np.ndarray:
    arr = np.array(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _detect_polys_bboxes(bgr_img: np.ndarray) -> List[Dict[str, Any]]:
    """Run detection using PaddleX detector and return list of dicts with polygon + bbox."""
    if create_model is None:
        raise HTTPException(status_code=500, detail=f"PaddleX not available: {paddlex_import_error}")
    init_paddle_models()
    assert paddle_detector is not None

    # Some PaddleX versions accept ndarray directly; for max compatibility write temp file
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
        cv2.imwrite(tmp_path, bgr_img)
    try:
        results = paddle_detector.predict(tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    items: List[Dict[str, Any]] = []
    if not isinstance(results, list):
        return items
    h_img, w_img = bgr_img.shape[:2]
    for result in results:
        boxes = result.get("dt_polys") if isinstance(result, dict) else None
        if not boxes:
            continue
        for poly in boxes:
            pts = np.array(poly, dtype=np.int32)
            x, y, w, h = cv2.boundingRect(pts)
            x1 = max(x, 0)
            y1 = max(y, 0)
            x2 = min(x + w, w_img)
            y2 = min(y + h, h_img)
            items.append({
                "polygon": poly,
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
            })
    return items


def _recognize_rois(bgr_img: np.ndarray, rois_info: List[Dict[str, Any]], min_conf: float) -> List[Dict[str, Any]]:
    """Run recognition using PaddleX recognizer for each ROI bbox and return enriched items."""
    if create_model is None:
        raise HTTPException(status_code=500, detail=f"PaddleX not available: {paddlex_import_error}")
    init_paddle_models()
    assert paddle_recognizer is not None

    results: List[Dict[str, Any]] = []
    h_img, w_img = bgr_img.shape[:2]
    for i, it in enumerate(rois_info, start=1):
        x1, y1, x2, y2 = it["bbox"]
        # clamp
        x1 = max(0, min(x1, w_img - 1))
        x2 = max(0, min(x2, w_img))
        y1 = max(0, min(y1, h_img - 1))
        y2 = max(0, min(y2, h_img))
        if x2 <= x1 or y2 <= y1:
            continue
        roi = bgr_img[y1:y2, x1:x2]
        if roi.size == 0:
            continue
        try:
            rec_gen = paddle_recognizer.predict(roi)
            text = ""
            score = 0.0
            try:
                rec = next(rec_gen)
                text = rec.get("rec_text", "")
                score = float(rec.get("rec_score", 0.0))
            except StopIteration:
                pass
        except Exception:
            text = ""
            score = 0.0
        if score >= min_conf:
            results.append({
                "box_id": i,
                "text": text,
                "confidence": score,
                "bbox": [int(x1), int(y1), int(x2), int(y2)],
                "polygon": it.get("polygon"),
            })
    return results


# ------------------------------- Endpoints ------------------------------- #

@app.post("/paddle/ocr-image")
async def paddle_ocr_image(
    _: bool = Depends(require_api_key),
    file: UploadFile = File(...),
    min_conf: float = Query(default=0.0, ge=0.0, le=1.0),
):
    if create_model is None:
        raise HTTPException(status_code=500, detail=f"PaddleX not available: {paddlex_import_error}")

    try:
        contents = await file.read()
        pil = Image.open(BytesIO(contents)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    bgr = _pil_to_bgr(pil)
    det_items = _detect_polys_bboxes(bgr)
    rec_items = _recognize_rois(bgr, det_items, min_conf=min_conf)

    return {
        "pages": 1,
        "dpi": None,
        "det_model": PADDLE_DET_MODEL,
        "rec_model": PADDLE_REC_MODEL,
        "items": rec_items,
        "text": "\n".join([it["text"] for it in rec_items if it.get("text")]),
    }


@app.post("/paddle/ocr-pdf")
async def paddle_ocr_pdf(
    _: bool = Depends(require_api_key),
    file: UploadFile = File(...),
    dpi: int = Query(default=300, ge=72, le=600),
    min_conf: float = Query(default=0.0, ge=0.0, le=1.0),
):
    if not PDF_AVAILABLE:
        raise HTTPException(status_code=500, detail="PDF support is not available on this server")
    if create_model is None:
        raise HTTPException(status_code=500, detail=f"PaddleX not available: {paddlex_import_error}")

    try:
        contents = await file.read()
        pages: List[Image.Image] = convert_from_bytes(contents, dpi=dpi)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid PDF file: {e}")

    all_items: List[Dict[str, Any]] = []
    for idx, pil in enumerate(pages, start=1):
        bgr = _pil_to_bgr(pil)
        det_items = _detect_polys_bboxes(bgr)
        rec_items = _recognize_rois(bgr, det_items, min_conf=min_conf)
        # annotate page number
        for it in rec_items:
            it["page"] = idx
        all_items.extend(rec_items)

    return {
        "pages": len(pages),
        "dpi": dpi,
        "det_model": PADDLE_DET_MODEL,
        "rec_model": PADDLE_REC_MODEL,
        "items": all_items,
        "text": "\n".join([it["text"] for it in all_items if it.get("text")]),
    }


# Keep a simple base OCR image endpoint for compatibility (EasyOCR/Tesseract users could add later)
@app.post("/ocr")
async def base_ocr_image(
    _: bool = Depends(require_api_key),
    file: UploadFile = File(...),
):
    try:
        contents = await file.read()
        pil = Image.open(BytesIO(contents)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    bgr = _pil_to_bgr(pil)
    det_items = _detect_polys_bboxes(bgr)
    rec_items = _recognize_rois(bgr, det_items, min_conf=0.0)
    return {"text": "\n".join([it["text"] for it in rec_items if it.get("text")])}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
