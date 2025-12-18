---
title: OCR Scan Vision API
emoji: 🧾
colorFrom: indigo
colorTo: blue
sdk: docker
pinned: false
license: mit
---

# OCR Scan Vision - Arabic Contract OCR API

FastAPI-based OCR service optimized for Arabic text extraction from contracts and documents using PaddleX.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info & status |
| GET | `/health` | Health check |
| POST | `/paddle/ocr-image` | OCR for images |
| POST | `/paddle/ocr-pdf` | OCR for PDF files |
| POST | `/ocr` | Simple OCR (text only) |

## API Usage

### OCR Image
```bash
curl -X POST "https://YOUR-SPACE.hf.space/paddle/ocr-image" \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@contract.jpg"
```

### OCR PDF
```bash
curl -X POST "https://YOUR-SPACE.hf.space/paddle/ocr-pdf?dpi=300" \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@contract.pdf"
```

### Response Format
```json
{
  "pages": 1,
  "det_model": "PP-OCRv5_server_det",
  "rec_model": "arabic_PP-OCRv5_mobile_rec",
  "items": [
    {
      "box_id": 1,
      "text": "النص المستخرج",
      "confidence": 0.95,
      "bbox": [x1, y1, x2, y2]
    }
  ],
  "text": "النص الكامل"
}
```

## Mobile Integration Example (Flutter)

```dart
import 'package:http/http.dart' as http;

Future<String> extractText(String imagePath) async {
  var request = http.MultipartRequest(
    'POST',
    Uri.parse('https://YOUR-SPACE.hf.space/paddle/ocr-image'),
  );
  request.headers['X-API-Key'] = 'YOUR_API_KEY';
  request.files.add(await http.MultipartFile.fromPath('file', imagePath));
  
  var response = await request.send();
  var body = await response.stream.bytesToString();
  return body; // Parse JSON to get text
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `API_KEY` | Optional API key for authentication | None |
| `PORT` | Server port | 7860 |

## Run Locally

```bash
pip install -r requirements.txt
python main.py
```

## Models Used
- Detection: `PP-OCRv5_server_det`
- Recognition: `arabic_PP-OCRv5_mobile_rec`
