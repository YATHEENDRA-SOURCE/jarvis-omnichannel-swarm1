import os
import json
import logging
import numpy as np
from typing import Optional, Tuple

logger = logging.getLogger("voice_security")


class VoiceSecurityManager:
    """Manages voiceprint enrollment and biometric speaker verification."""

    def __init__(self, profile_path: str = "voiceprint_profile.json"):
        self.profile_path = profile_path
        self.enrolled = os.path.exists(self.profile_path)
        self.reference_features = self._load_profile()

    def _extract_audio_features(self, audio_data: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """Extracts frequency spectrum and energy distribution signature."""
        if len(audio_data) == 0:
            return np.zeros(32)
        
        # FFT spectrum analysis
        fft_vals = np.abs(np.fft.rfft(audio_data))
        freqs = np.fft.rfftfreq(len(audio_data), 1.0 / sample_rate)

        # 32 sub-band energy buckets
        bands = np.array_split(fft_vals, 32)
        band_energies = np.array([np.mean(b) if len(b) > 0 else 0.0 for b in bands])
        
        # Normalize
        norm = np.linalg.norm(band_energies)
        if norm > 0:
            band_energies = band_energies / norm
        return band_energies

    def _load_profile(self) -> Optional[np.ndarray]:
        if not os.path.exists(self.profile_path):
            return None
        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return np.array(data.get("features", []))
        except Exception as e:
            logger.error(f"Failed to load voice profile: {e}")
            return None

    def enroll_voice(self, audio_data: np.ndarray, sample_rate: int = 16000) -> bool:
        """Saves user's voice signature to create their unique voiceprint."""
        try:
            features = self._extract_audio_features(audio_data, sample_rate)
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump({"features": features.tolist(), "created_at": "2026-08-31"}, f, indent=2)
            self.reference_features = features
            self.enrolled = True
            logger.info("Voiceprint enrollment successful!")
            return True
        except Exception as e:
            logger.error(f"Enrollment failed: {e}")
            return False

    def verify_speaker(self, audio_data: np.ndarray, sample_rate: int = 16000, threshold: float = 0.70) -> Tuple[bool, float]:
        """
        Verifies if incoming speech matches the enrolled owner's voice.
        Returns (is_verified, similarity_score).
        """
        if self.reference_features is None or len(self.reference_features) == 0:
            # If not enrolled yet, allow by default
            return True, 1.0

        current_features = self._extract_audio_features(audio_data, sample_rate)
        # Cosine similarity
        similarity = float(np.dot(self.reference_features, current_features))
        is_match = similarity >= threshold
        logger.info(f"Speaker Verification: Similarity={similarity:.3f}, Verified={is_match}")
        return is_match, similarity
