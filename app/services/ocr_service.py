"""OCR service for extracting text from scanned documents."""

import logging
from pathlib import Path
from typing import Optional

import pytesseract
from PIL import Image
from pdf2image import convert_from_path

from app.config import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


class OCRService:
    """Service for performing OCR on scanned documents."""
    
    def __init__(self):
        """Initialize the OCR service."""
        # Verify Tesseract is available
        try:
            pytesseract.get_tesseract_version()
            logger.info("Tesseract OCR initialized successfully")
        except Exception as e:
            logger.warning(f"Tesseract OCR may not be properly installed: {e}")
    
    def extract_text(self, file_path: Path) -> Optional[str]:
        """
        Extract text from a document file.
        
        Args:
            file_path: Path to the document file (PDF or image)
            
        Returns:
            Extracted text or None if extraction failed
        """
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return None
        
        suffix = file_path.suffix.lower()
        
        if suffix not in SUPPORTED_EXTENSIONS:
            logger.error(f"Unsupported file type: {suffix}")
            return None
        
        try:
            if suffix == ".pdf":
                return self._extract_from_pdf(file_path)
            else:
                return self._extract_from_image(file_path)
        except Exception as e:
            logger.error(f"OCR extraction failed for {file_path}: {e}")
            return None
    
    def _extract_from_image(self, image_path: Path) -> str:
        """
        Extract text from an image file.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Extracted text
        """
        logger.info(f"Extracting text from image: {image_path}")
        
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (for RGBA images)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Perform OCR
            text = pytesseract.image_to_string(img, lang='eng')
        
        logger.info(f"Extracted {len(text)} characters from {image_path}")
        return text.strip()
    
    def _extract_from_pdf(self, pdf_path: Path) -> str:
        """
        Extract text from a PDF file by converting pages to images.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Extracted text from all pages
        """
        logger.info(f"Extracting text from PDF: {pdf_path}")
        
        # Convert PDF pages to images
        pages = convert_from_path(pdf_path, dpi=300)
        
        all_text = []
        for i, page in enumerate(pages):
            logger.info(f"Processing page {i + 1}/{len(pages)}")
            
            # Convert to RGB if necessary
            if page.mode in ('RGBA', 'P'):
                page = page.convert('RGB')
            
            # Perform OCR on this page
            page_text = pytesseract.image_to_string(page, lang='eng')
            all_text.append(page_text.strip())
        
        combined_text = "\n\n".join(all_text)
        logger.info(f"Extracted {len(combined_text)} characters from {len(pages)} pages")
        return combined_text


# Global OCR service instance
ocr_service = OCRService()

