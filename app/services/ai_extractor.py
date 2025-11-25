"""AI-powered field extraction service using OpenAI."""

import json
import logging
from typing import Optional
from datetime import datetime

from openai import OpenAI

from app.config import OPENAI_API_KEY
from app.schemas import ExtractedFields

logger = logging.getLogger(__name__)


class AIExtractorService:
    """Service for extracting structured fields from OCR text using AI."""
    
    EXTRACTION_PROMPT = """You are an expert at extracting information from educational documents.
Given the OCR text from a scanned student document, extract the following fields:

1. course_name: The name of the course or class
2. student_name: The full name of the student
3. assignment_name: The name or title of the assignment, test, or exercise
4. grade: The grade or score received (e.g., "A", "85%", "42/50")
5. document_date: The date on the document (in YYYY-MM-DD format if possible)

If a field cannot be determined from the text, set it to null.
Also provide a confidence score from 0.0 to 1.0 indicating how confident you are in the extractions.

Respond ONLY with a JSON object in this exact format:
{
    "course_name": "string or null",
    "student_name": "string or null",
    "assignment_name": "string or null",
    "grade": "string or null",
    "document_date": "YYYY-MM-DD or null",
    "confidence": 0.0
}

OCR Text:
"""

    def __init__(self):
        """Initialize the AI extractor service."""
        self.client = None
        if OPENAI_API_KEY:
            try:
                self.client = OpenAI(api_key=OPENAI_API_KEY)
                logger.info("OpenAI client initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")
        else:
            logger.warning("OpenAI API key not configured - AI extraction will be unavailable")
    
    def extract_fields(self, ocr_text: str) -> ExtractedFields:
        """
        Extract structured fields from OCR text using AI.
        
        Args:
            ocr_text: The text extracted from the document via OCR
            
        Returns:
            ExtractedFields object with the extracted information
        """
        if not self.client:
            logger.warning("OpenAI client not available, returning empty fields")
            return ExtractedFields()
        
        if not ocr_text or not ocr_text.strip():
            logger.warning("Empty OCR text provided")
            return ExtractedFields()
        
        try:
            # Truncate text if too long (to stay within token limits)
            max_chars = 4000
            text_to_process = ocr_text[:max_chars] if len(ocr_text) > max_chars else ocr_text
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You extract information from educational documents and respond only with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": self.EXTRACTION_PROMPT + text_to_process
                    }
                ],
                temperature=0.1,  # Low temperature for consistent extraction
                max_tokens=500
            )
            
            # Parse the response
            response_text = response.choices[0].message.content.strip()
            logger.debug(f"AI response: {response_text}")
            
            # Try to parse JSON from the response
            extracted_data = self._parse_json_response(response_text)
            
            if extracted_data:
                return ExtractedFields(**extracted_data)
            else:
                logger.warning("Failed to parse AI response as JSON")
                return ExtractedFields()
                
        except Exception as e:
            logger.error(f"AI extraction failed: {e}")
            return ExtractedFields()
    
    def _parse_json_response(self, response_text: str) -> Optional[dict]:
        """
        Parse JSON from the AI response, handling potential formatting issues.
        
        Args:
            response_text: The raw response text from the AI
            
        Returns:
            Parsed dictionary or None if parsing failed
        """
        # Try direct JSON parsing first
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON object in the response
        try:
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start != -1 and end > start:
                json_str = response_text[start:end]
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        return None
    
    def validate_date(self, date_str: Optional[str]) -> Optional[str]:
        """
        Validate and normalize a date string.
        
        Args:
            date_str: Date string to validate
            
        Returns:
            Normalized date string in YYYY-MM-DD format or None
        """
        if not date_str:
            return None
        
        # Common date formats to try
        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(date_str.strip(), fmt)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue
        
        return None


# Global AI extractor service instance
ai_extractor_service = AIExtractorService()

