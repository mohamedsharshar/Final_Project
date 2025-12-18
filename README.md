---
title: OCR Scan Vision API
emoji: 🧾
colorFrom: indigo
colorTo: blue
sdk: docker
pinned: false
license: mit
---

# Arabic OCR API

Simple API for extracting Arabic text from contract images.

## Endpoint

**POST** `/ocr`

### Request
- `file`: Image file (multipart/form-data)
- `min_conf`: Minimum confidence threshold (0.0-1.0, optional)

### Response
```json
{
  "items": [
    {"box_id": 1, "text": "النص", "confidence": 0.95, "bbox": [x1,y1,x2,y2]}
  ],
  "text": "النص الكامل",
  "total_boxes": 10
}
```

## Usage

```bash
curl -X POST "https://sharshar1-ocr.hf.space/ocr" -F "file=@image.jpg"
```
