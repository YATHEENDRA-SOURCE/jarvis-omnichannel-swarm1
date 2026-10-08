import os
import sys
import logging
import webview

from whatsapp_web import WhatsAppWebController
from agent import UniversalAIAgent
from voice import VoiceEngine
from voice_security import VoiceSecurityManager
from jarvis_bridge import JarvisBridgeAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("JARVIS_APP")


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def setup_global_hotkey(bridge: JarvisBridgeAPI):
    """Sets up a system-wide hotkey (Ctrl + Space) to trigger JARVIS from anywhere in Windows."""
    try:
        import keyboard
        def on_hotkey():
            logger.info("Global hotkey (Ctrl + Space) triggered!")
            bridge.listen_and_execute()
            
        keyboard.add_hotkey("ctrl+space", on_hotkey)
        logger.info("Global hotkey [Ctrl + Space] registered.")
    except Exception as e:
        logger.warning(f"Global hotkey setup note: {e}")


def main():
    print("=" * 60)
    print("      [+] STARTING J.A.R.V.I.S. OMNI-CHANNEL AGENT")
    print("=" * 60)

    # 1. Initialize WhatsApp Web Controller
    wa_controller = WhatsAppWebController()

    # 2. Initialize Agent, Voice, and Security
    agent = UniversalAIAgent(wa_controller)
    voice_engine = VoiceEngine(tts_enabled=True)
    security = VoiceSecurityManager()

    # 3. Create Bridge API (Initializes WhatsApp on its unified background event loop)
    bridge = JarvisBridgeAPI(agent=agent, voice_engine=voice_engine, security=security)
    setup_global_hotkey(bridge)

    # Start always-on wake word listener
    bridge.start_wake_word_listener()
    logger.info("Wake word listener started. Say 'JARVIS' to activate!")

    # 4. Launch Desktop Window
    ui_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "ui", "index.html"))
    
    window = webview.create_window(
        title="J.A.R.V.I.S. - AI Desktop Agent",
        url=ui_path,
        js_api=bridge,
        width=1020,
        height=700,
        resizable=True,
        frameless=False,
        easy_drag=True,
        background_color="#020617",
    )
    bridge.set_window(window)

    webview.start(debug=False)


if __name__ == "__main__":
    main()
