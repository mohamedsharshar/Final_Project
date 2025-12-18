from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
from io import BytesIO
from PIL import Image
import uvicorn
import os
import numpy as np
import cv2

# PDF support
try:
    from pdf2image import convert_from_bytes
    PDF_AVAILABLE = True
except:
    PDF_AVAILABLE = False

# Models
paddle_detector = None
paddle_recognizer = None

app = FastAPI(title="OCR Scan Vision API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    print("Server started. OCR models will be loaded lazily on first request.")


def get_models():
    global paddle_detector, paddle_recognizer

    if paddle_detector is None or paddle_recognizer is None:
        try:
            from paddlex import create_model
            print("Loading PaddleX OCR models...")
            paddle_detector = create_model("PP-OCRv5_server_det")
            paddle_recognizer = create_model("arabic_PP-OCRv5_mobile_rec")
            print("Models loaded.")
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"OCR models failed to load: {str(e)}"
            )

    return paddle_detector, paddle_recognizer


def process_image(img: np.ndarray, detector, recognizer, min_conf: float) -> List[Dict]:
    """Process single image and return OCR results."""
    h_img, w_img = img.shape[:2]
    
    # Step 1: Detect text regions
    results = detector.predict(img)
    
    all_rois = []
    all_bboxes = []
    
    for result in results:
        boxes = result.get("dt_polys", [])
        for box in boxes:
            pts = np.array(box, dtype=np.int32)
            x, y, w, h = cv2.boundingRect(pts)
            x1 = max(x, 0)
            y1 = max(y, 0)
            x2 = min(x + w, w_img)
            y2 = min(y + h, h_img)
            
            if x2 > x1 and y2 > y1:
                roi = img[y1:y2, x1:x2]
                if roi.size > 0:
                    all_rois.append(roi)
                    all_bboxes.append([int(x1), int(y1), int(x2), int(y2)])
    
    # Step 2: Recognize text in each ROI
    ocr_results = []
    
    for i, roi in enumerate(all_rois):
        try:
            rec_generator = recognizer.predict(roi)
            rec = next(rec_generator)
            text = rec.get("rec_text", "")
            score = float(rec.get("rec_score", 0.0))
        except:
            text = ""
            score = 0.0
        
        if score >= min_conf:
            ocr_results.append({
                "box_id": i + 1,
                "text": text,
                "confidence": round(score, 4),
                "bbox": all_bboxes[i]
            })
    
    return ocr_results


@app.get("/")
def root():
    return {"name": "OCR Scan Vision API", "status": "ok", "pdf_support": PDF_AVAILABLE}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/ocr")
async def ocr_image(
    file: UploadFile = File(...),
    min_conf: float = Query(default=0.0, ge=0.0, le=1.0),
):
    """OCR for images (JPG, PNG, etc.)"""
    try:
        contents = await file.read()
        pil_img = Image.open(BytesIO(contents)).convert("RGB")
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except:
        raise HTTPException(status_code=400, detail="Invalid image file")
    
    detector, recognizer = get_models()
    ocr_results = process_image(img, detector, recognizer, min_conf)
    full_text = "\n".join([r["text"] for r in ocr_results if r["text"]])
    
    return {
        "items": ocr_results,
        "text": full_text,
        "total_boxes": len(ocr_results)
    }


@app.post("/ocr-pdf")
async def ocr_pdf(
    file: UploadFile = File(...),
    dpi: int = Query(default=300, ge=72, le=600),
    min_conf: float = Query(default=0.0, ge=0.0, le=1.0),
):
    """OCR for PDF files - converts each page to image then extracts text."""
    if not PDF_AVAILABLE:
        raise HTTPException(status_code=500, detail="PDF support not available")
    
    try:
        contents = await file.read()
        pages = convert_from_bytes(contents, dpi=dpi)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid PDF file: {e}")
    
    detector, recognizer = get_models()
    
    all_results = []
    all_text = []
    
    for page_num, pil_img in enumerate(pages, start=1):
        img = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
        page_results = process_image(img, detector, recognizer, min_conf)
        
        # Add page number to each result
        for item in page_results:
            item["page"] = page_num
        
        all_results.extend(page_results)
        page_text = "\n".join([r["text"] for r in page_results if r["text"]])
        if page_text:
            all_text.append(f"--- Page {page_num} ---\n{page_text}")
    
    return {
        "pages": len(pages),
        "items": all_results,
        "text": "\n\n".join(all_text),
        "total_boxes": len(all_results)
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
