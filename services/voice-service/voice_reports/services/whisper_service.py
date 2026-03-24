"""
Whisper Integration Service

Reuses existing Whisper STT and Text-to-SQL components from Small Whisper.
This is an integration layer, NOT a reimplementation.
"""

import sys
import os
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class WhisperIntegrationService:
    """
    Integration service that calls existing Whisper STT model.
    Reuses components from Small Whisper folder.
    """
    
    def __init__(self):
        """Initialize Whisper integration by importing existing modules."""
        self._setup_small_whisper_path()
        self._import_whisper_components()
    
    def _setup_small_whisper_path(self):
        """Add Small Whisper to Python path."""
        try:
            # Get Small Whisper backend path
            current_dir = Path(__file__).resolve().parent.parent.parent
            small_whisper_backend = current_dir / 'Small Whisper' / 'backend'
            
            if small_whisper_backend.exists():
                sys.path.insert(0, str(small_whisper_backend))
                logger.info(f"Added Small Whisper to path: {small_whisper_backend}")
            else:
                logger.error(f"Small Whisper backend not found at: {small_whisper_backend}")
                raise FileNotFoundError(f"Small Whisper backend not found")
        
        except Exception as e:
            logger.error(f"Failed to setup Small Whisper path: {e}")
            raise
    
    def _import_whisper_components(self):
        """Import existing Whisper model and components."""
        try:
            # Import existing Whisper model
            import whisper
            self.whisper = whisper
            
            # Load model (reuse existing model)
            download_root = os.path.expanduser("~/.cache/whisper")
            self.model = whisper.load_model("large-v3", download_root=download_root)
            
            logger.info("Whisper model loaded successfully (reusing existing)")
            
            # Import existing pipeline
            try:
                from shared.pipeline import process_after_whisper
                self.process_after_whisper = process_after_whisper
                logger.info("Imported existing pipeline from Small Whisper")
            except ImportError as e:
                logger.warning(f"Could not import pipeline: {e}")
                self.process_after_whisper = None
        
        except Exception as e:
            logger.error(f"Failed to import Whisper components: {e}")
            raise
    
    def transcribe_audio(self, audio_file_path, language='en', task='transcribe'):
        """
        Transcribe audio using existing Whisper model.
        
        Args:
            audio_file_path: Path to audio file
            language: Language code (default: 'en')
            task: 'transcribe' or 'translate'
        
        Returns:
            dict: {
                'text': transcribed text,
                'language': detected language,
                'segments': segments with timestamps
            }
        """
        try:
            logger.info(f"Transcribing audio: {audio_file_path}")
            
            # Call existing Whisper model
            result = self.model.transcribe(
                audio_file_path,
                language=language if language else None,
                task=task
            )
            
            logger.info(f"Transcription successful: {len(result['text'])} characters")
            
            return {
                'text': result['text'],
                'language': result.get('language', language),
                'segments': result.get('segments', []),
                'duration': sum(seg.get('end', 0) - seg.get('start', 0) 
                               for seg in result.get('segments', []))
            }
        
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise
    
    def transcribe_from_django_file(self, django_file):
        """
        Transcribe audio from Django UploadedFile.
        
        Args:
            django_file: Django UploadedFile object
        
        Returns:
            dict: Transcription result
        """
        try:
            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp:
                for chunk in django_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            
            try:
                # Transcribe
                result = self.transcribe_audio(tmp_path)
                return result
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        
        except Exception as e:
            logger.error(f"Failed to transcribe Django file: {e}")
            raise
    
    def process_full_pipeline(self, text):
        """
        Process text through existing Text-to-SQL pipeline.
        
        Args:
            text: Transcribed text
        
        Returns:
            dict: {
                'reasoning': reasoning output,
                'llm': LLM output with SQL and intent
            }
        """
        try:
            if self.process_after_whisper:
                logger.info("Processing through existing pipeline")
                reasoning_result, llm_result = self.process_after_whisper(text)
                
                return {
                    'reasoning': reasoning_result,
                    'llm': llm_result
                }
            else:
                logger.warning("Pipeline not available, returning text only")
                return {
                    'reasoning': None,
                    'llm': None
                }
        
        except Exception as e:
            logger.error(f"Pipeline processing failed: {e}")
            raise


# Singleton instance
_whisper_service = None

def get_whisper_service():
    """Get or create Whisper service singleton."""
    global _whisper_service
    if _whisper_service is None:
        _whisper_service = WhisperIntegrationService()
    return _whisper_service

