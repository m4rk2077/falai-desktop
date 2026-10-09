"""
Transcription History Manager
Stores all transcriptions with timestamps
"""
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Union

from src.utils.logger import get_logger
from src.utils.app_paths import get_history_path
from src.security.local_crypto import LocalCrypto

logger = get_logger(__name__)


class TranscriptionHistory:
    """Manages transcription history with persistence"""
    
    def __init__(self, history_file: Union[str, Path, None] = None):
        self.history_file = Path(history_file) if history_file is not None else get_history_path()
        self.legacy_history_file = self.history_file.with_suffix(".json")
        self.crypto = LocalCrypto()
        self.history: List[Dict] = []
        self._migrate_legacy_history()
        self._load()

    def _migrate_legacy_history(self) -> None:
        """Migrate legacy plaintext history to encrypted storage."""
        try:
            if self.history_file.exists():
                return
            legacy_candidates = [self.legacy_history_file, Path("data") / "history.json"]
            try:
                project_root = Path(__file__).resolve().parents[2]
                legacy_candidates.append(project_root / "data" / "history.json")
            except Exception:
                pass

            legacy_path = None
            for p in legacy_candidates:
                try:
                    if p.exists():
                        legacy_path = p
                        break
                except Exception:
                    continue
            if not legacy_path:
                return

            self.crypto.migrate_json_file(legacy_path, self.history_file, default_obj=[])
            logger.info("History migrated to encrypted storage: %s", self.history_file)
        except Exception:
            logger.warning("Could not migrate legacy history to encrypted storage", exc_info=True)
    
    def _load(self):
        """Load history from file"""
        try:
            if self.history_file.exists():
                obj = self.crypto.read_json(self.history_file, default=[])
                self.history = obj if isinstance(obj, list) else []
                logger.info("Loaded %s history items", len(self.history))
        except Exception as e:
            logger.error("Could not load history", exc_info=True)
            self.history = []
    
    def _save(self):
        """Save history to file"""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            self.crypto.write_json(self.history_file, self.history)
        except Exception as e:
            logger.error("Could not save history", exc_info=True)
    
    def add(
        self,
        original: str,
        corrected: Optional[str] = None,
        duration_seconds: float = 0,
        transcription_id: Optional[str] = None,
    ) -> Dict:
        """
        Add a new transcription to history
        
        Args:
            original: Original transcription from Whisper
            corrected: GPT-corrected text (optional)
            duration_seconds: Audio duration
        
        Returns:
            The created history entry
        """
        entry = {
            "id": len(self.history) + 1,
            "timestamp": datetime.now().isoformat(),
            "original": original,
            "corrected": corrected,
            "duration_seconds": round(duration_seconds, 2),
        }
        tid = str(transcription_id or "").strip()
        if tid:
            entry["transcription_id"] = tid
        
        self.history.append(entry)
        self._save()
        
        return entry

    def update_corrected_by_transcription_id(self, transcription_id: str, corrected: Optional[str]) -> bool:
        """Update an existing history row with a refined corrected text.

        Returns True when an entry was updated.
        """
        tid = str(transcription_id or "").strip()
        if not tid:
            return False

        corrected_txt = str(corrected or "").strip() or None
        updated = False
        for entry in reversed(self.history):
            if str(entry.get("transcription_id") or "").strip() != tid:
                continue
            if corrected_txt:
                entry["corrected"] = corrected_txt
            updated = True
            break

        if updated:
            self._save()
        return updated
    
    def get_all(self, limit: int = 50) -> List[Dict]:
        """Get all history entries (most recent first)"""
        return list(reversed(self.history[-limit:]))
    
    def get_by_id(self, entry_id: int) -> Optional[Dict]:
        """Get a specific entry by ID"""
        for entry in self.history:
            if entry["id"] == entry_id:
                return entry
        return None
    
    def search(self, query: str) -> List[Dict]:
        """Search history by text content"""
        query_lower = query.lower()
        results = []
        
        for entry in self.history:
            original = entry.get("original", "").lower()
            corrected = entry.get("corrected", "") or ""
            
            if query_lower in original or query_lower in corrected.lower():
                results.append(entry)
        
        return list(reversed(results))
    
    def clear(self):
        """Clear all history"""
        self.history = []
        self._save()
        logger.info("History cleared")
    
    def get_text(self, entry: Dict) -> str:
        """Get the best text from an entry (corrected if available)"""
        return entry.get("corrected") or entry.get("original", "")
