from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
import uvicorn
import logging
import time

from .models import OCRRequest, OCRResponse
from .ocr_engine import process_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("ocr_service.api")

app = FastAPI(
    title="Search & Rescue Room Label OCR API",
    description="Microservice for extracting text from drone frames",
    version="1.0.0"
)

# Optional: Add CORS middleware if the drone frontend needs to call this directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/v1/ocr/room-label", response_model=OCRResponse)
async def extract_room_label(request: OCRRequest, raw_request: Request):
    """
    Analyzes a base64 encoded image frame and returns the detected text blocks.
    """
    request_id = raw_request.headers.get("x-ocr-request-id") or f"srv-{int(time.time() * 1000)}"
    room_idx = raw_request.headers.get("x-room-index", "unknown")
    payload_len = len(request.image_base64 or "")
    logger.info(
        "[OCR][%s] request primit room=%s payload_base64_len=%s",
        request_id,
        room_idx,
        payload_len,
    )

    try:
        result = process_image(request.image_base64, request_id=request_id)
        logger.info("[OCR][%s] response trimis results=%d", request_id, len(result.results))
        return result
    except Exception as e:
        logger.exception("[OCR][%s] eroare procesare: %s", request_id, e)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
