from pydantic import BaseModel, Field
from typing import List, Tuple, Any

class OCRRequest(BaseModel):
    image_base64: str = Field(description="Base64 encoded image string of the frame containing the room label")

class DetectedText(BaseModel):
    text: str = Field(description="The detected string")
    confidence: float = Field(description="Confidence score of the OCR prediction (0.0 to 1.0)")
    bounding_box: List[List[float]] = Field(description="Bounding box coordinates [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]")

class OCRResponse(BaseModel):
    results: List[DetectedText] = Field(description="A list of all text blocks detected in the image")
