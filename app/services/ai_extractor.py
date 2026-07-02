"""AI-powered field extraction service using OpenAI."""

import json
import logging
import time
from typing import Optional
from datetime import datetime

from openai import OpenAI

from app.config import OPENAI_API_KEY
from app.schemas import ExtractedFields
from app.services.llm import safe_chat_completion

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
6. student_id: A 13-digit government/ID number if present (e.g. 0501015513085 or 8711115189080). Omit if not found.

If a field cannot be determined from the text, set it to null.
Also provide a confidence score from 0.0 to 1.0 indicating how confident you are in the extractions.

Respond ONLY with a JSON object in this exact format:
{
    "course_name": "string or null",
    "student_name": "string or null",
    "assignment_name": "string or null",
    "grade": "string or null",
    "document_date": "YYYY-MM-DD or null",
    "student_id": "13 digits or null",
    "confidence": 0.0
}

OCR Text:
"""

    def __init__(self):
        """Initialize the AI extractor service.

        Clients are built per call from runtime settings (provider, model, API
        key, base URL) rather than at import, so config changes made on the
        Settings page take effect without a restart.
        """
        pass

    def _resolve_config(self, config: Optional[dict]) -> dict:
        """Use the passed config, or fall back to environment defaults."""
        if config:
            return config
        return {
            "enabled": bool(OPENAI_API_KEY),
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": OPENAI_API_KEY,
            "base_url": None,
        }

    def test_connection(self, config: dict) -> dict:
        """
        Make a minimal round-trip to verify the provider/model/key/base_url.

        Returns {ok, message, model, response, latency_ms}.
        """
        config = config or {}
        api_key = config.get("api_key")
        model = config.get("model") or "gpt-4o-mini"
        if not api_key:
            return {"ok": False, "message": "No API key configured.", "model": model}
        try:
            client = OpenAI(api_key=api_key, base_url=config.get("base_url") or None)
            start = time.perf_counter()
            response = safe_chat_completion(
                client,
                model,
                [{"role": "user", "content": "Reply with the single word: OK"}],
                100,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            text = (response.choices[0].message.content or "").strip()
            return {
                "ok": True,
                "message": "Connection successful",
                "model": model,
                "response": text,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            return {"ok": False, "message": f"{type(exc).__name__}: {exc}", "model": model}

    def extract_fields(self, ocr_text: str, config: Optional[dict] = None) -> ExtractedFields:
        """
        Extract structured fields from OCR text using AI.

        Args:
            ocr_text: The text extracted from the document via OCR
            config: Resolved AI config (enabled, provider, model, api_key,
                base_url). Falls back to environment when omitted.

        Returns:
            ExtractedFields object with the extracted information
        """
        cfg = self._resolve_config(config)

        if not cfg.get("enabled") or not cfg.get("api_key"):
            logger.warning("AI extraction disabled or no API key; returning empty fields")
            return ExtractedFields()

        if not ocr_text or not ocr_text.strip():
            logger.warning("Empty OCR text provided")
            return ExtractedFields()

        try:
            client = OpenAI(api_key=cfg["api_key"], base_url=cfg.get("base_url") or None)

            # Truncate text if too long (to stay within token limits)
            max_chars = 4000
            text_to_process = ocr_text[:max_chars] if len(ocr_text) > max_chars else ocr_text

            messages = [
                {
                    "role": "system",
                    "content": "You extract information from educational documents and respond only with valid JSON.",
                },
                {
                    "role": "user",
                    "content": self.EXTRACTION_PROMPT + text_to_process,
                },
            ]
            response = safe_chat_completion(
                client, cfg.get("model") or "gpt-4o-mini", messages, 500
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

