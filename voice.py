import os
import re
import time
import threading
import logging
from typing import Optional

logger = logging.getLogger("voice_engine")


class VoiceEngine:
    """Handles microphone speech-to-text and asynchronous text-to-speech feedback."""

    def __init__(self, tts_enabled: bool = True):
        self.tts_enabled = tts_enabled
        self.sp_voice = None
        if self.tts_enabled:
            try:
                import win32com.client
                self.sp_voice = win32com.client.Dispatch("SAPI.SpVoice")
                self.sp_voice.Rate = 1  # Conversational rate
                self.sp_voice.Volume = 100
                logger.info("Native Windows SAPI.SpVoice initialized successfully.")
            except Exception as e:
                logger.warning(f"SAPI.SpVoice init note: {e}")

    def listen(self, prompt_msg: str = "🎙️ JARVIS Listening...") -> Optional[str]:
        """Listens from the default microphone and converts speech to text."""
        try:
            import speech_recognition as sr
        except ImportError:
            logger.error("SpeechRecognition is not installed.")
            return None

        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        recognizer.dynamic_energy_adjustment_damping = 0.15
        recognizer.dynamic_energy_ratio = 1.4
        recognizer.pause_threshold = 0.8  # Stop 0.8s after speech ends
        recognizer.non_speaking_duration = 0.5

        try:
            with sr.Microphone() as source:
                print(f"\n{prompt_msg}")
                # Fast ambient calibration
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                logger.info(f"Microphone calibrated. Energy threshold: {recognizer.energy_threshold:.1f}")
                audio = recognizer.listen(source, timeout=6, phrase_time_limit=14)
                logger.info("Processing speech with Google Speech Recognition...")
                text = recognizer.recognize_google(audio)
                logger.info(f"Voice Transcribed: '{text}'")
                return text
        except sr.WaitTimeoutError:
            logger.info("Listening timed out (no speech detected).")
            return None
        except sr.UnknownValueError:
            logger.info("Could not understand audio.")
            return None
        except Exception as e:
            logger.error(f"Microphone error: {e}")
            return None

    def speak(self, text: str):
        """Speaks text asynchronously using native Windows SAPI voice."""
        if not self.tts_enabled or not text:
            return

        # Clean markdown, URLs, symbols, and emojis for clean, natural human speech
        clean = re.sub(r'https?://\S+', 'link', text)
        clean = re.sub(r'[*_#`•>\-\[\]\(\)]', ' ', clean)
        clean = re.sub(r'[^\w\s.,!?:;\'"]', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if not clean:
            return

        speech_text = clean[:320]
        logger.info(f"Speaking aloud: '{speech_text}'")

        def _speak_worker(msg):
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                sp = win32com.client.Dispatch("SAPI.SpVoice")
                sp.Rate = 1
                sp.Volume = 100
                sp.Speak(msg, 0)  # Synchronous inside worker thread
                pythoncom.CoUninitialize()
            except Exception as e:
                logger.warning(f"Thread SAPI speak error: {e}")
                # Fallback: PowerShell SpeechSynthesizer
                try:
                    import subprocess
                    escaped = msg.replace('"', ' ').replace("'", " ")
                    ps_cmd = f'Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = 1; $s.Speak("{escaped}")'
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command", ps_cmd],
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        timeout=15
                    )
                except Exception as ps_err:
                    logger.error(f"Fallback speech error: {ps_err}")

        # Fire speech worker in background thread so caller never blocks
        t = threading.Thread(target=_speak_worker, args=(speech_text,), daemon=True)
        t.start()
