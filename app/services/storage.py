"""Storage service for optimizing and storing documents."""

import logging
import shutil
import uuid
from datetime import datetime
import re
from pathlib import Path
from typing import Tuple, Optional

from PIL import Image
from pdf2image import convert_from_path

from app.config import (
    STORAGE_PATH,
    STORAGE_REVIEW_PATH,
    MAX_IMAGE_DIMENSION,
    JPEG_QUALITY,
    POPPLER_PATH,
)

logger = logging.getLogger(__name__)


class StorageService:
    """Service for optimizing and storing scanned documents."""
    
    def __init__(self):
        """Initialize the storage service."""
        self.storage_path = STORAGE_PATH
        self.review_path = STORAGE_REVIEW_PATH
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.review_path.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Storage service initialized with paths: final=%s review=%s",
            self.storage_path,
            self.review_path,
        )
    
    def store_document(self, source_path: Path) -> Tuple[str, Path]:
        """
        Optimize and store a document.
        
        Args:
            source_path: Path to the source document
            
        Returns:
            Tuple of (document_id, stored_path)
        """
        # Generate unique document ID
        doc_id = str(uuid.uuid4())
        
        # Create date-based subdirectory for organization
        date_dir = datetime.now().strftime("%Y/%m/%d")
        target_dir = (self.storage_path / date_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_dir = target_dir.resolve()

        suffix = source_path.suffix.lower()

        try:
            if suffix == ".pdf":
                stored_path = self._store_pdf(source_path, target_dir, doc_id)
            else:
                stored_path = self._store_image(source_path, target_dir, doc_id)

            logger.info(f"Document stored: {stored_path}")
            return doc_id, stored_path.resolve()

        except Exception as e:
            logger.error(f"Failed to store document {source_path}: {e}")
            raise
    
    def _store_image(self, source_path: Path, target_dir: Path, doc_id: str) -> Path:
        """
        Optimize and store an image file.
        
        Args:
            source_path: Path to the source image
            target_dir: Directory to store the optimized image
            doc_id: Document ID for the filename
            
        Returns:
            Path to the stored image
        """
        target_path = target_dir / f"{doc_id}.jpg"
        
        with Image.open(source_path) as img:
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'P', 'LA', 'L'):
                # Create white background for transparent images
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                else:
                    img = img.convert('RGB')
            
            # Resize if too large while maintaining aspect ratio
            img = self._resize_if_needed(img)
            
            # Save optimized image
            img.save(target_path, 'JPEG', quality=JPEG_QUALITY, optimize=True)
        
        return target_path
    
    def _store_pdf(self, source_path: Path, target_dir: Path, doc_id: str) -> Path:
        """
        Store a PDF file, optionally converting to optimized images.
        
        For PDFs, we keep the original but also create optimized preview images.
        
        Args:
            source_path: Path to the source PDF
            target_dir: Directory to store the document
            doc_id: Document ID for the filename
            
        Returns:
            Path to the stored PDF
        """
        # Copy the original PDF
        target_path = target_dir / f"{doc_id}.pdf"
        shutil.copy2(source_path, target_path)
        
        # Create preview images for each page
        try:
            preview_dir = target_dir / f"{doc_id}_previews"
            preview_dir.mkdir(exist_ok=True)
            
            pages = convert_from_path(source_path, dpi=150, poppler_path=POPPLER_PATH)  # Lower DPI for previews
            
            for i, page in enumerate(pages):
                preview_path = preview_dir / f"page_{i + 1}.jpg"
                
                # Convert to RGB if necessary
                if page.mode != 'RGB':
                    page = page.convert('RGB')
                
                # Resize if needed
                page = self._resize_if_needed(page)
                
                # Save preview
                page.save(preview_path, 'JPEG', quality=JPEG_QUALITY, optimize=True)
            
            logger.info(f"Created {len(pages)} preview images for PDF")
            
        except Exception as e:
            logger.warning(f"Failed to create PDF previews: {e}")
        
        return target_path
    
    def _resize_if_needed(self, img: Image.Image) -> Image.Image:
        """
        Resize an image if it exceeds the maximum dimension.
        
        Args:
            img: PIL Image to resize
            
        Returns:
            Resized image (or original if no resize needed)
        """
        width, height = img.size
        
        if width <= MAX_IMAGE_DIMENSION and height <= MAX_IMAGE_DIMENSION:
            return img
        
        # Calculate new dimensions maintaining aspect ratio
        if width > height:
            new_width = MAX_IMAGE_DIMENSION
            new_height = int(height * (MAX_IMAGE_DIMENSION / width))
        else:
            new_height = MAX_IMAGE_DIMENSION
            new_width = int(width * (MAX_IMAGE_DIMENSION / height))
        
        return img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    def _sanitize_filename_part(self, s: Optional[str], max_len: int = 80) -> str:
        """
        Make a string safe for use as a filename segment.
        Replaces spaces and unsafe chars with underscore, strips, truncates.
        """
        if not s or not str(s).strip():
            return "Unknown"
        # Replace spaces, slashes, backslashes, and other problematic chars with single underscore
        out = re.sub(r"[\s/\\<>:\"|?*\x00-\x1f]+", "_", str(s).strip())
        out = out.strip("._ ")
        if not out:
            return "Unknown"
        return out[:max_len] if len(out) > max_len else out

    def rename_to_descriptive(
        self,
        stored_path: str,
        student_name: Optional[str] = None,
        course_name: Optional[str] = None,
        document_type: Optional[str] = None,
        student_id: Optional[str] = None,
    ) -> str:
        """
        Rename a stored file to a descriptive name: StudentName_CourseName_Type_Last4.ext.
        Handles uniqueness by appending _1, _2, ... if the name already exists.
        Returns the new stored path (same format as input: relative or absolute).
        """
        path = self._ensure_absolute(stored_path)
        if not path.exists():
            logger.warning("Cannot rename missing file: %s", stored_path)
            return stored_path

        ext = path.suffix or ""
        last4 = "XXXX"
        if student_id and len(str(student_id).strip()) >= 4:
            last4 = str(student_id).strip()[-4:]

        # Keep the type as a safe filename segment; supports any configured
        # type key, not just the original poe/certificate pair.
        type_part = re.sub(r"[^a-z0-9_-]+", "", (document_type or "poe").strip().lower()) or "poe"

        parts = [
            self._sanitize_filename_part(student_name),
            self._sanitize_filename_part(course_name),
            type_part,
            last4,
        ]
        base_name = "_".join(parts)
        # Cap total base name length to avoid filesystem issues (e.g. 200 chars)
        if len(base_name) > 200:
            base_name = base_name[:200].rstrip("_")

        target_dir = path.parent
        candidate_stem = base_name
        counter = 0
        while True:
            new_name = f"{candidate_stem}{ext}"
            target_file = target_dir / new_name
            if not target_file.exists():
                break
            counter += 1
            candidate_stem = f"{base_name}_{counter}"

        # Rename main file
        target_file = target_dir / f"{candidate_stem}{ext}"
        path.rename(target_file)

        # Rename preview directory if present (PDFs)
        old_preview_dir = path.parent / f"{path.stem}_previews"
        if old_preview_dir.exists():
            new_preview_dir = target_file.parent / f"{target_file.stem}_previews"
            if new_preview_dir.exists():
                shutil.rmtree(new_preview_dir)
            shutil.move(str(old_preview_dir), str(new_preview_dir))

        # Return path in same style as input (relative from storage base if input was relative)
        try:
            rel = target_file.relative_to(self.storage_path)
            result = str(rel)
        except ValueError:
            try:
                rel = target_file.relative_to(self.review_path)
                result = str(rel)
            except ValueError:
                result = str(target_file)

        logger.info("Renamed document to descriptive name: %s", result)
        return result
    
    def _ensure_absolute(self, path_str: str) -> Path:
        path = Path(path_str)
        if path.is_absolute():
            return path

        if path.parts and path.parts[0] == self.storage_path.name:
            return (self.storage_path.parent / path).resolve()
        if path.parts and path.parts[0] == self.review_path.name:
            return (self.review_path.parent / path).resolve()

        candidate = (self.storage_path / path).resolve()
        if candidate.exists():
            return candidate

        candidate = (self.review_path / path).resolve()
        return candidate

    @staticmethod
    def _is_under(path: Path, base: Path) -> bool:
        """True if path is inside base (or equal to it)."""
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False

    def _relative_to_known_base(self, path: Path) -> Path:
        """
        Path relative to whichever known base contains it.

        The review path may be nested under the storage path (default:
        storage/review_queue), so the more specific base is checked first.
        Otherwise a review file would keep its "review_queue/..." prefix and
        never actually leave the review folder when moved to final storage.
        """
        bases = sorted(
            {self.storage_path.resolve(), self.review_path.resolve()},
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for base in bases:
            try:
                return path.relative_to(base)
            except ValueError:
                continue
        return Path(path.name)

    def move_to_review_storage(self, stored_path: str) -> str:
        return str(self._move_between_bases(stored_path, self.review_path))

    def move_to_final_storage(self, stored_path: str) -> str:
        return str(self._move_between_bases(stored_path, self.storage_path))

    def _is_already_located(self, source: Path, destination_base: Path) -> bool:
        """
        Whether `source` is already correctly placed for `destination_base`.

        Final storage means "under the storage path but NOT under the review
        path", because the review folder is itself nested under storage. Without
        this distinction a review file counts as already-in-final and is never
        moved out of the review queue (the original bug).
        """
        review = self.review_path.resolve()
        storage = self.storage_path.resolve()
        if destination_base.resolve() == review:
            return self._is_under(source, review)
        return self._is_under(source, storage) and not self._is_under(source, review)

    def _move_between_bases(self, stored_path: str, destination_base: Path) -> Path:
        source = self._ensure_absolute(stored_path).resolve()
        if not source.exists():
            logger.warning("Attempted to move missing file: %s", stored_path)
            return source

        destination_base = destination_base.resolve()

        if self._is_already_located(source, destination_base):
            return source  # already in the correct tree

        relative = self._relative_to_known_base(source)
        target_dir = destination_base / relative.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / relative.name

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), target)

        preview_dir = source.parent / f"{source.stem}_previews"
        if preview_dir.exists():
            new_preview_parent = target.parent / f"{target.stem}_previews"
            if new_preview_parent.exists():
                shutil.rmtree(new_preview_parent)
            shutil.move(str(preview_dir), new_preview_parent)

        logger.info("Moved %s to %s", stored_path, target)
        return target

    def get_document_path(self, stored_path: str) -> Optional[Path]:
        """
        Get the full path to a stored document.
        
        Args:
            stored_path: Relative or absolute path to the document
            
        Returns:
            Full path to the document or None if not found
        """
        path = self._ensure_absolute(stored_path)
        return path if path.exists() else None
    
    def get_preview_paths(self, stored_path: str) -> list[Path]:
        """
        Get preview image paths for a PDF document.
        
        Args:
            stored_path: Path to the stored PDF
            
        Returns:
            List of absolute preview image paths
        """
        path = self._ensure_absolute(stored_path)
        if not path.exists():
            return []
        preview_dir = path.parent / f"{path.stem}_previews"
        if not preview_dir.exists():
            return []
        return sorted(preview_dir.glob("page_*.jpg"))
    
    def delete_document(self, stored_path: str) -> bool:
        """
        Delete a stored document and its previews.
        
        Args:
            stored_path: Path to the stored document
            
        Returns:
            True if deletion was successful
        """
        try:
            path = self._ensure_absolute(stored_path)
            
            # Delete the main file
            if path.exists():
                path.unlink()
            
            # Delete preview directory if it exists (for PDFs)
            preview_dir = path.parent / f"{path.stem}_previews"
            if preview_dir.exists():
                shutil.rmtree(preview_dir)
            
            logger.info(f"Deleted document: {stored_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete document {stored_path}: {e}")
            return False


# Global storage service instance
storage_service = StorageService()

