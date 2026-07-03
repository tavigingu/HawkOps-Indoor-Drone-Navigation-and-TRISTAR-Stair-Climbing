import base64
import numpy as np
import cv2
import easyocr
import logging
from .models import OCRResponse, DetectedText

logger = logging.getLogger("ocr_service.engine")

# Initialize the EasyOCR reader at startup so models are loaded into memory once.
# This will download the models to ~/.EasyOCR/model on the first ever run.
print("Loading EasyOCR models (en, ro)...")
reader = easyocr.Reader(['en', 'ro'])
print("EasyOCR loaded successfully.")

def process_image(base64_image: str, request_id: str = "n/a") -> OCRResponse:
    """
    Decodes the base64 image into a numpy array / cv2 image,
    runs EasyOCR to extract text, and maps the results to Pydantic models.
    """
    # 1. Decode base64 to bytes
    img_bytes = base64.b64decode(base64_image)
    
    # 2. Convert to numpy array
    np_arr = np.frombuffer(img_bytes, np.uint8)
    
    # 3. Decode into a cv2 image format
    img_cv2 = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    
    if img_cv2 is None:
         raise ValueError("Failed to decode image from base64 string")

    img_h, img_w = img_cv2.shape[:2]
    logger.info("[OCR][%s] imagine decodată %dx%d (%d bytes)", request_id, img_w, img_h, len(img_bytes))

    # 4. Run EasyOCR inference
    # readtext returns a list of tuples: (bounding_box, text, confidence)
    results_raw = reader.readtext(img_cv2)
    
    # 5. Format results into the expected response schema
    detected_items = []
    for bbox, text, conf in results_raw:
        # Convert bbox items to standard float lists for JSON serialization
        # bbox is typically a list of 4 points: [[x,y], [x,y], [x,y], [x,y]]
        formatted_bbox = [[float(pt[0]), float(pt[1])] for pt in bbox]
        
        detected_items.append(DetectedText(
            text=text,
            confidence=float(conf),
            bounding_box=formatted_bbox
        ))

    if detected_items:
        top_item = max(detected_items, key=lambda item: item.confidence)
        logger.info(
            "[OCR][%s] detectii=%d top='%s' conf=%.3f",
            request_id,
            len(detected_items),
            top_item.text,
            top_item.confidence,
        )
    else:
        logger.info("[OCR][%s] detectii=0", request_id)
        
    return OCRResponse(results=detected_items)
