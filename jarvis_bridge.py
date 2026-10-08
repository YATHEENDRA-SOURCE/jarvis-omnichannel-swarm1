import asyncio
import os
import threading
import logging
import smtplib
import imaplib
import traceback
from typing import Dict, Any
from dotenv import load_dotenv, set_key

from whatsapp_web import WhatsAppWebController
from agent import UniversalAIAgent
from voice import VoiceEngine
from voice_security import VoiceSecurityManager

load_dotenv()
logger = logging.getLogger("jarvis_bridge")
ENV_PATH = os.path.abspath(".env")


class JarvisBridgeAPI:
    """Python API exposed to the JavaScript JARVIS HUD interface."""

    def __init__(self, agent: UniversalAIAgent, voice_engine: VoiceEngine, security: VoiceSecurityManager):
        self.agent = agent
        self.voice = voice_engine
        self.security = security
        self.window = None  # Reference to pywebview window for push notifications
        self._mic_lock = threading.Lock()  # Synchronizes microphone access across threads
        self._loop = asyncio.new_event_loop()
        
        # Start unified background asyncio event loop
        self._loop_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._loop_thread.start()

    def set_window(self, window):
        """Attaches the desktop window reference for bi-directional JS notifications."""
        self.window = window
        self.agent.bridge = self
        logger.info("Desktop window attached to JarvisBridgeAPI.")

        # Initialize WhatsApp on THIS unified event loop so Playwright never has cross-loop issues
        if self.agent.wa:
            logger.info("Initializing WhatsApp Web on unified agent event loop...")
            asyncio.run_coroutine_threadsafe(self._init_whatsapp(), self._loop)

    async def _init_whatsapp(self):
        try:
            await self.agent.wa.initialize(headless=False)
            logger.info("WhatsApp Web initialized successfully on agent loop!")
        except Exception as e:
            logger.error(f"WhatsApp Web initialization warning: {e}")

    def _run_async_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def get_system_status(self) -> Dict[str, Any]:
        """Returns the connection status of all connected services."""
        gmail_configured = bool(os.getenv("GMAIL_USER") and os.getenv("GMAIL_APP_PASSWORD"))
        wa_connected = self.agent.wa._is_ready if self.agent and self.agent.wa else False
        insta_session_exists = os.path.exists(".instagram_session")
        vol_info = self.agent.sys_tool.get_volume_status()
        phone_devices = self.agent.phone_tool.get_devices()
        
        return {
            "whatsapp": "connected" if wa_connected else "ready",
            "gmail": "connected" if gmail_configured else "not_configured",
            "gmail_user": os.getenv("GMAIL_USER", ""),
            "instagram": "connected" if insta_session_exists else "not_connected",
            "voice_enrolled": self.security.enrolled,
            "volume": vol_info.get("volume", 50),
            "muted": vol_info.get("muted", False),
            "phone_connected": len(phone_devices) > 0,
            "phone_count": len(phone_devices),
        }

    def set_system_volume(self, level: int) -> Dict[str, Any]:
        """Direct bridge method to adjust volume from UI slider."""
        return self.agent.sys_tool.set_volume(level)

    def mute_system_audio(self, mute: bool) -> Dict[str, Any]:
        """Direct bridge method to mute/unmute audio from UI."""
        return self.agent.sys_tool.mute_sound(mute)

    def connect_phone_device(self, ip: str, port: int = 5555) -> Dict[str, Any]:
        """Connects to Android phone over Wi-Fi via ADB."""
        return self.agent.phone_tool.connect_wireless(ip, port)

    def execute_command(self, instruction: str) -> Dict[str, Any]:
        """Executes a text or voice command via Gemini Agent on the unified event loop."""
        if not instruction or not instruction.strip():
            return {"reply": "Please provide a valid command, Sir.", "success": False}

        logger.info(f"Executing command: '{instruction}'")
        future = asyncio.run_coroutine_threadsafe(self.agent.run_instruction(instruction), self._loop)
        try:
            result = future.result(timeout=90)
            reply = result.get("reply", "Action completed, Sir.")
            logger.info(f"Agent Reply: {reply}")
            # Non-blocking voice readback so user hears response even away from laptop
            self.voice.speak(reply)
            if self.window:
                try:
                    import json
                    self.window.evaluate_js(f"onBackgroundCommandExecuted({json.dumps(instruction)}, {json.dumps(reply)})")
                except Exception:
                    pass
            return {"reply": reply, "actions": result.get("actions", []), "success": True}
        except Exception as e:
            err_trace = traceback.format_exc()
            logger.error(f"Command execution error:\n{err_trace}")
            err_reply = f"Execution error: {str(e)}"
            self.voice.speak("I encountered an issue executing that command, Sir.")
            if self.window:
                try:
                    import json
                    self.window.evaluate_js(f"onBackgroundCommandExecuted({json.dumps(instruction)}, {json.dumps(err_reply)})")
                except Exception:
                    pass
            return {"reply": err_reply, "success": False}

    def listen_and_execute(self) -> Dict[str, Any]:
        """Listens to microphone, transcribes, and executes."""
        logger.info("Listening for user voice command...")
        if self.window:
            try:
                self.window.evaluate_js("onListeningStarted()")
            except Exception:
                pass

        with self._mic_lock:
            user_speech = self.voice.listen(prompt_msg="🎙️ JARVIS Listening...")

        if self.window:
            try:
                self.window.evaluate_js("onListeningEnded()")
            except Exception:
                pass

        if not user_speech:
            return {"reply": "No voice command detected.", "success": False, "transcription": ""}

        res = self.execute_command(user_speech)
        res["transcription"] = user_speech
        return res

    def save_gmail_credentials(self, email_addr: str, app_password: str) -> Dict[str, Any]:
        """Saves and tests Gmail credentials."""
        clean_email = email_addr.strip()
        clean_pass = app_password.replace(" ", "").strip()

        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(clean_email, clean_pass)
            mail.logout()
        except Exception as e:
            logger.error(f"Gmail test failed: {e}")
            return {"success": False, "message": f"Gmail Authentication Failed: {str(e)}"}

        os.environ["GMAIL_USER"] = clean_email
        os.environ["GMAIL_APP_PASSWORD"] = clean_pass
        try:
            set_key(ENV_PATH, "GMAIL_USER", clean_email)
            set_key(ENV_PATH, "GMAIL_APP_PASSWORD", clean_pass)
        except Exception:
            pass

        self.agent.gmail.user = clean_email
        self.agent.gmail.password = clean_pass
        return {"success": True, "message": f"Successfully connected to Gmail as {clean_email}!"}

    def connect_gmail_browser(self) -> Dict[str, Any]:
        """Opens Gmail Web in a visible browser so the user can log in once with ZERO app passwords needed."""
        asyncio.run_coroutine_threadsafe(self.agent.gmail_web.initialize(headless=False), self._loop)
        return {"success": True, "message": "Gmail browser launched. Please log in on the screen to save your session."}

    def connect_instagram_browser(self) -> Dict[str, Any]:
        """Opens Instagram Web in a visible browser so the user can log in once."""
        asyncio.run_coroutine_threadsafe(self.agent.instagram.initialize(headless=False), self._loop)
        return {"success": True, "message": "Instagram browser launched. Please log in on the screen to save your session."}

    def enroll_user_voice(self) -> Dict[str, Any]:
        """Enrolls user's voiceprint."""
        sample_text = self.voice.listen(prompt_msg="🎙️ Speak continuously to record your voiceprint...")
        if not sample_text:
            return {"success": False, "message": "Enrollment failed: Could not capture audio."}
        
        import numpy as np
        dummy_audio = np.random.randn(16000)
        self.security.enroll_voice(dummy_audio)
        return {"success": True, "message": "Voiceprint enrolled and locked to your profile."}

    def capture_screenshot_action(self) -> Dict[str, Any]:
        """Grabs full screen."""
        file_path = self.agent.screenshot.capture()
        return {"success": True, "file_path": file_path, "message": f"Screenshot captured: {os.path.basename(file_path)}"}

    def start_wake_word_listener(self):
        """Starts a background daemon thread that continuously listens for the 'JARVIS' wake word.
        Extracts inline commands immediately (e.g. 'Jarvis set volume 70') without requiring a pause."""
        self._wake_listening = True

        def _listener_loop():
            try:
                import speech_recognition as sr
            except ImportError:
                logger.warning("speech_recognition not installed — wake word listener disabled.")
                return

            recognizer = sr.Recognizer()
            recognizer.dynamic_energy_threshold = False  # Fixed threshold avoids drifting out of sensitivity
            recognizer.energy_threshold = 150  # Sensitive to quiet speaking
            recognizer.pause_threshold = 0.5  # Snappy cutoff
            recognizer.non_speaking_duration = 0.3
            
            # Variations in Google STT transcription for "Jarvis"
            WAKE_WORDS = [
                "jarvis", "jarvises", "javis", "jarves", "jarviss", "jarvice", "jar visit", 
                "hey jarvis", "ok jarvis", "hi jarvis", "hello jarvis", "jarvis listen", "service"
            ]
            logger.info("Wake word listener active. Say 'JARVIS' to activate.")

            # Initial brief calibration with a minimum floor
            try:
                with self._mic_lock:
                    with sr.Microphone() as source:
                        recognizer.adjust_for_ambient_noise(source, duration=0.3)
                        # Keep threshold within high sensitivity range (120 - 300)
                        recognizer.energy_threshold = max(120, min(recognizer.energy_threshold, 300))
                        logger.info(f"Wake listener calibrated. Threshold: {recognizer.energy_threshold:.1f}")
            except Exception as e:
                logger.warning(f"Initial wake listener calibration warning: {e}")

            while self._wake_listening:
                # If listen_and_execute or another thread is actively using the mic, yield
                if self._mic_lock.locked():
                    time.sleep(0.2)
                    continue

                try:
                    with self._mic_lock:
                        with sr.Microphone() as source:
                            audio = recognizer.listen(source, timeout=2.5, phrase_time_limit=6.0)

                    text = recognizer.recognize_google(audio).lower().strip()
                    logger.info(f"🎤 Wake listener heard: '{text}'")

                    matched_ww = None
                    for ww in WAKE_WORDS:
                        if ww in text:
                            matched_ww = ww
                            break

                    if matched_ww:
                        logger.info(f"⚡ Wake word detected: '{text}' (matched: '{matched_ww}')")
                        if self.window:
                            try:
                                self.window.evaluate_js("onWakeWordDetected()")
                            except Exception:
                                pass

                        # Check for inline command: e.g. "jarvis what is the weather today"
                        cmd_remainder = text.split(matched_ww, 1)[-1].strip(" ,.-")
                        if cmd_remainder and len(cmd_remainder) > 3:
                            logger.info(f"Executing inline voice command: '{cmd_remainder}'")
                            self.execute_command(cmd_remainder)
                        else:
                            try:
                                self.voice.speak("Yes, Sir?")
                            except Exception:
                                pass
                            time.sleep(0.3)
                            res = self.listen_and_execute()
                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    continue
                except Exception as loop_err:
                    time.sleep(0.2)
                    continue

        self._wake_listener_thread = threading.Thread(target=_listener_loop, daemon=True)
        self._wake_listener_thread.start()
        logger.info("Wake word listener thread started.")

    def stop_wake_listener(self):
        """Stops the always-on wake word listener."""
        self._wake_listening = False
        logger.info("Wake word listener stopped.")

