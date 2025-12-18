import os
import re
import cv2
import numpy as np
import uvicorn
from io import BytesIO
from typing import List, Dict
from PIL import Image
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# دعم ملفات PDF
try:
    from pdf2image import convert_from_bytes
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# تعريف متغيرات النماذج بشكل عالمي (Global)
paddle_detector = None
paddle_recognizer = None

app = FastAPI(title="OCR Scan Vision API", version="1.0.0")

# إعدادات الـ CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- تنظيف النص العربي --------------------
def smart_clean_arabic_text(text: str) -> str:
    """
    وظيفة لتنظيف النص المستخرج من OCR ومعالجة مشاكل الحروف المقطعة.
    """
    if not text:
        return ""

    # تحويل الرموز المهمة لمساحات مؤقتاً
    text = re.sub(r"[:\-_/]", " ", text)

    # 1. معالجة تفتيت "ال" التعريف: إزالة المسافة بين الألف واللام
    text = re.sub(r"([اأإ])\s+([ل])", r"\1\2", text)

    # 2. معالجة تفتيت الكلمات بعد الحروف غير المتصلة (مثل و، ر، د، ز، د)
    text = re.sub(r"([اأإدذرزو])\s+([\u0600-\u06FF])", r"\1\2", text)

    # 3. تنظيف علامات الاقتباس والرموز الخاصة
    text = re.sub(r"[«»“”‘’]", "", text)

    # 4. ضبط المسافات حول علامات الترقيم
    text = re.sub(r"\s*([.,;?!])\s*", r"\1 ", text)
    text = re.sub(r"\s*([()])\s*", r" \1 ", text)

    # 5. تنظيف المسافات الزائدة حول الشرطة
    text = re.sub(r"\s*-\s*", r"-", text)

    # 6. التنظيف الأساسي: الاحتفاظ بالعربي والأرقام فقط
    text = re.sub(r"[^\u0600-\u06FF0-9\s]", "", text)

    # 7. إزالة التشكيل (Tashkeel)
    text = re.sub(r"[\u064B-\u065F]", "", text)

    # 8. إزالة المسافات المتكررة
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def get_models():
    """تحميل نماذج OCR عند الحاجة فقط (Lazy Loading)"""
    global paddle_detector, paddle_recognizer

    if paddle_detector is None or paddle_recognizer is None:
        try:
            from paddlex import create_model
            print("Loading PaddleX OCR models...")
            # تأكد من أن أسماء النماذج صحيحة حسب إصدار PaddleX لديك
            paddle_detector = create_model("PP-OCRv5_server_det")
            paddle_recognizer = create_model("arabic_PP-OCRv5_mobile_rec")
            print("Models loaded successfully.")
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"OCR models failed to load: {str(e)}"
            )

    return paddle_detector, paddle_recognizer


def process_image(img: np.ndarray, detector, recognizer, min_conf: float) -> List[Dict]:
    """معالجة صورة واحدة واستخراج النصوص منها"""
    h_img, w_img = img.shape[:2]

    # 1️⃣ كشف أماكن النصوص (Detection)
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
                    all_bboxes.append([x1, y1, x2, y2])

    # 2️⃣ التعرف على محتوى النصوص (Recognition)
    ocr_results = []

    for i, roi in enumerate(all_rois):
        try:
            rec_gen = recognizer.predict(roi)
            rec = next(rec_gen)
            raw_text = rec.get("rec_text", "")
            score = float(rec.get("rec_score", 0.0))
            text = smart_clean_arabic_text(raw_text)
        except Exception:
            text = ""
            score = 0.0

        if score >= min_conf and text:
            ocr_results.append({
                "box_id": i + 1,
                "text": text,
                "confidence": round(score, 4),
                "bbox": all_bboxes[i]
            })

    # ✅ ترتيب عربي: من الأعلى للأسفل، ومن اليمين لليسار
    ocr_results.sort(
        key=lambda x: (
            x["bbox"][1],     # الترتيب الرأسي (Y)
            -x["bbox"][0]     # الترتيب الأفقي العكسي (X) لليمين
        )
    )

    return ocr_results


# -------------------- Endpoints --------------------

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
    try:
        contents = await file.read()
        pil_img = Image.open(BytesIO(contents)).convert("RGB")
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    detector, recognizer = get_models()
    ocr_results = process_image(img, detector, recognizer, min_conf)

    # تجميع النص الكامل
    full_text = "\n".join([r["text"] for r in ocr_results])

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
    if not PDF_AVAILABLE:
        raise HTTPException(status_code=500, detail="PDF support not available (poppler might be missing)")

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

        for item in page_results:
            item["page"] = page_num

        all_results.extend(page_results)

        page_text = "\n".join([r["text"] for r in page_results])
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
    uvicorn.run(app, host="0.0.0.0", port=port)