import json
import logging
import os
import re
import asyncio
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

from whatsapp_web import WhatsAppWebController
from tools.screenshot_tool import ScreenshotTool
from tools.files_tool import FilesTool
from tools.gmail_tool import GmailTool
from tools.gmail_web import GmailWebController
from tools.instagram_tool import InstagramWebController
from tools.system_os_tool import SystemOSTool
from tools.docs_notepad_tool import DocsNotepadTool
from tools.weather_tool import WeatherTool
from tools.phone_tool import PhoneTool

load_dotenv()
logger = logging.getLogger("JARVIS_SWARM")


class ContactsManager:
    """Manages address book in JSON."""
    def __init__(self, filepath: str = "contacts.json"):
        self.filepath = filepath

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.filepath):
            return {"contacts": []}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"contacts": []}

    def _save(self, data: Dict[str, Any]):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_all(self) -> List[Dict[str, str]]:
        return self._load().get("contacts", [])

    def lookup(self, query: str) -> Optional[Dict[str, str]]:
        q = query.lower().strip()
        contacts = self.get_all()
        for c in contacts:
            if c.get("name", "").lower() == q:
                return c
        for c in contacts:
            if q in c.get("name", "").lower() or q in c.get("notes", "").lower():
                return c
        return None

    def add_or_update(self, name: str, phone: str, notes: str = "") -> Dict[str, Any]:
        clean_phone = WhatsAppWebController.sanitize_phone(phone)
        data = self._load()
        contacts = data.get("contacts", [])
        for c in contacts:
            if c.get("name", "").lower() == name.lower():
                c["phone"] = clean_phone
                if notes:
                    c["notes"] = notes
                self._save(data)
                return {"success": True, "contact": c}

        new_c = {"name": name, "phone": clean_phone, "notes": notes}
        contacts.append(new_c)
        self._save(data)
        return {"success": True, "contact": new_c}


# =====================================================================
# SPECIALIZED SUB-AGENTS
# =====================================================================

class CommAgent:
    """Specialist sub-agent for WhatsApp, Instagram DMs, Gmail, and Voice/Video Calling."""

    def __init__(self, wa: Optional[WhatsAppWebController], insta: InstagramWebController, gmail: GmailTool, gmail_web: GmailWebController, contacts: ContactsManager, files: FilesTool, screenshot: ScreenshotTool):
        self.wa = wa
        self.insta = insta
        self.gmail = gmail
        self.gmail_web = gmail_web
        self.contacts = contacts
        self.files = files
        self.screenshot = screenshot

    async def send_whatsapp_message(self, recipient: str, message: str) -> Dict[str, Any]:
        if not self.wa:
            return {"success": False, "error": "WhatsApp Web is not initialized."}
        contact = self.contacts.lookup(recipient)
        target = contact["phone"] if contact and contact.get("phone") else recipient
        res = await self.wa.send_message(recipient=target, message=message)
        disp = f"{contact['name']} (+{target})" if contact else (f"+{target}" if (target.isdigit() or target.startswith('+')) else target)
        res["recipient_display"] = disp
        return res

    async def send_file_attachment(self, target: str, file_query: str, caption: str = "") -> Dict[str, Any]:
        if not self.wa:
            return {"success": False, "error": "WhatsApp Web is not initialized."}
        resolved = self.files.find_file(file_query)
        if not resolved:
            return {"success": False, "error": f"File '{file_query}' could not be located on PC."}
        return await self.wa.send_file_attachment(target=target, file_path=resolved, caption=caption)

    async def send_screenshot(self, target: Optional[str] = None, caption: str = "Here is the screenshot.") -> Dict[str, Any]:
        shot_path = self.screenshot.capture()
        if target and self.wa:
            res = await self.wa.send_file_attachment(target=target, file_path=shot_path, caption=caption)
            res["screenshot_path"] = shot_path
            return res
        return {"success": True, "file_path": shot_path, "message": f"Screenshot captured at {shot_path}"}

    async def make_call(self, app: str, recipient: str, is_video: bool = False) -> Dict[str, Any]:
        if "whatsapp" in app.lower():
            if not self.wa:
                return {"success": False, "error": "WhatsApp Web is not initialized."}
            return await self.wa.make_call(target=recipient, is_video=is_video)
        elif "instagram" in app.lower():
            return {"success": True, "message": f"Opening Instagram Direct to call {recipient}."}
        return {"success": False, "error": f"Unsupported call platform: {app}"}

    async def hangup_call(self, app: str = "whatsapp") -> Dict[str, Any]:
        if "whatsapp" in app.lower() and self.wa:
            return await self.wa.hangup_call()
        return {"success": False, "message": "No active call found to hang up."}

    async def send_email(self, to_email: str, subject: str, body: str, attachment: Optional[str] = None) -> Dict[str, Any]:
        resolved_attach = self.files.find_file(attachment) if attachment else None
        try:
            return self.gmail.send_email(to_email=to_email, subject=subject, body=body, attachment_path=resolved_attach)
        except Exception as e:
            logger.info(f"Using Gmail Web fallback: {e}")
            return await self.gmail_web.send_email(to=to_email, subject=subject, body=body)

    async def read_unread_emails(self, limit: int = 5) -> Dict[str, Any]:
        try:
            emails = self.gmail.read_unread_emails(max_count=limit)
            return {"unread_emails": emails}
        except Exception as e:
            logger.info(f"Using Gmail Web fallback for inbox: {e}")
            emails = await self.gmail_web.read_unread_emails(max_count=limit)
            return {"unread_emails": emails, "source": "Gmail Web"}

    async def send_instagram_dm(self, username: str, message: str) -> Dict[str, Any]:
        return await self.insta.send_dm(username=username, message=message)


class SystemAgent:
    """Specialist sub-agent for Windows hardware controls, audio, Wi-Fi, window management, and desktop apps."""

    def __init__(self, sys_tool: SystemOSTool):
        self.sys = sys_tool

    def control_audio(self, action: str, level: int = 50) -> Dict[str, Any]:
        act = action.lower().strip()
        if "set" in act or "volume" in act:
            return self.sys.set_volume(level)
        elif "mute" in act and "un" not in act:
            return self.sys.mute_sound(True)
        elif "unmute" in act or "resume" in act:
            return self.sys.mute_sound(False)
        return self.sys.get_volume_status()

    def toggle_wifi(self, state: str) -> Dict[str, Any]:
        return self.sys.toggle_wifi(state)

    def window_management(self, action: str) -> Dict[str, Any]:
        act = action.lower().strip()
        if "terminal" in act:
            return self.sys.minimize_terminals()
        elif "desktop" in act or "minimize_all" in act or "all" in act:
            return self.sys.minimize_all_windows()
        return self.sys.minimize_terminals()

    def launch_calculator(self) -> Dict[str, Any]:
        return self.sys.open_calculator()

    def calculate_math(self, expression: str) -> Dict[str, Any]:
        return self.sys.calculate_math(expression)

    def search_web(self, browser: str, query: str) -> Dict[str, Any]:
        return self.sys.browser_search(browser=browser, query_or_url=query)

    def open_files_folder(self, folder: str = "downloads") -> Dict[str, Any]:
        return self.sys.open_files_folder(folder)

    def launch_vscode(self, path: Optional[str] = None) -> Dict[str, Any]:
        return self.sys.open_vscode(path)


class DevAgent:
    """Specialist sub-agent for writing software, creating projects, and opening them in VS Code."""

    def __init__(self, docs_tool: DocsNotepadTool, sys_tool: SystemOSTool):
        self.docs = docs_tool
        self.sys = sys_tool

    def create_code(self, code: str, filename: str, project_dir: Optional[str] = None, open_vscode: bool = True) -> Dict[str, Any]:
        return self.docs.generate_code(code=code, filename=filename, project_dir=project_dir, open_vscode=open_vscode)


class DocsAgent:
    """Specialist sub-agent for Notepad dictation, Word documents, and Weather intelligence."""

    def __init__(self, docs_tool: DocsNotepadTool, weather_tool: WeatherTool):
        self.docs = docs_tool
        self.weather = weather_tool

    def take_note(self, text: str, filename: Optional[str] = None, open_notepad: bool = True) -> Dict[str, Any]:
        return self.docs.take_note(text=text, filename=filename, open_editor=open_notepad)

    def create_word_doc(self, title: str, content: str, filename: Optional[str] = None, open_word: bool = True) -> Dict[str, Any]:
        return self.docs.create_word_document(title=title, content=content, filename=filename, open_word=open_word)

    def get_weather(self, location: Optional[str] = None) -> Dict[str, Any]:
        return self.weather.get_weather(location=location)


class PhoneAgent:
    """Specialist sub-agent for Android device control via ADB (Wireless & USB)."""

    def __init__(self, phone_tool: PhoneTool):
        self.phone = phone_tool

    def get_battery(self) -> Dict[str, Any]:
        return self.phone.get_battery_status()

    def launch_app(self, app_name: str) -> Dict[str, Any]:
        return self.phone.launch_phone_app(app_name)

    def ring_phone(self) -> Dict[str, Any]:
        return self.phone.ring_phone()

    def control_volume(self, action: str) -> Dict[str, Any]:
        return self.phone.control_phone_volume(action)

    def toggle_screen(self) -> Dict[str, Any]:
        return self.phone.lock_unlock_screen()

    def unlock(self, pin: Optional[str] = None) -> Dict[str, Any]:
        return self.phone.unlock_phone(pin)

    def lock(self) -> Dict[str, Any]:
        return self.phone.lock_phone()

    def set_pin(self, pin: str) -> Dict[str, Any]:
        return self.phone.set_phone_pin(pin)

    def play_song(self, song_name: str, app: str = "youtube") -> Dict[str, Any]:
        return self.phone.play_song_on_phone(song_name, app)

    def stop_song(self) -> Dict[str, Any]:
        return self.phone.stop_song_on_phone()

    def skip_ad(self) -> Dict[str, Any]:
        return self.phone.skip_youtube_ad()

    def type_text(self, text: str, proceed: bool = True) -> Dict[str, Any]:
        return self.phone.type_text_on_phone(text, proceed)

    def connect(self, ip: str, port: int = 5555) -> Dict[str, Any]:
        return self.phone.connect_wireless(ip, port)


class VisionAgent:
    """Specialist sub-agent for screen vision and GUI automation."""

    def __init__(self, vision_tool):
        self.vision = vision_tool

    def analyze_screen(self, gemini_client, model, question="What is on the screen?"):
        return self.vision.analyze_screen(gemini_client, model, question)

    def find_and_click(self, gemini_client, model, element):
        return self.vision.find_element_and_click(gemini_client, model, element)

    def click_at(self, x, y, double=False):
        return self.vision.screen_click(x, y, double)

    def type_text(self, text):
        return self.vision.screen_type(text)

    def press_key(self, key_combo):
        return self.vision.screen_key(key_combo)

    def scroll(self, direction, amount=3):
        return self.vision.screen_scroll(direction, amount)

    def snap_windows(self, app1, app2):
        return self.vision.arrange_windows_split(app1, app2)


# =====================================================================
# J.A.R.V.I.S. MASTER ORCHESTRATOR SWARM
# =====================================================================

class UniversalAIAgent:
    """Master J.A.R.V.I.S. Orchestrator commanding the specialized Multi-Agent Swarm."""

    def __init__(self, wa_controller: Optional[WhatsAppWebController]):
        self.wa = wa_controller
        self.contacts = ContactsManager()
        self.screenshot = ScreenshotTool()
        self.files = FilesTool()
        self.gmail = GmailTool()
        self.gmail_web = GmailWebController()
        self.instagram = InstagramWebController()
        self.sys_tool = SystemOSTool()
        self.docs_tool = DocsNotepadTool()
        self.weather_tool = WeatherTool()
        self.phone_tool = PhoneTool()

        # Initialize Sub-Agents with Unique Marvel/Stark Swarm Codenames
        self.friday = CommAgent(
            wa=self.wa,
            insta=self.instagram,
            gmail=self.gmail,
            gmail_web=self.gmail_web,
            contacts=self.contacts,
            files=self.files,
            screenshot=self.screenshot,
        )
        self.ultron = SystemAgent(sys_tool=self.sys_tool)
        self.stark = DevAgent(docs_tool=self.docs_tool, sys_tool=self.sys_tool)
        self.jocasta = DocsAgent(docs_tool=self.docs_tool, weather_tool=self.weather_tool)
        self.rhodey = PhoneAgent(phone_tool=self.phone_tool)

        # Vision sub-agent (E.D.I.T.H.)
        from tools.vision_agent_tool import VisionAgentTool
        self.vision_tool = VisionAgentTool()
        self.edith = VisionAgent(vision_tool=self.vision_tool)

        # Backwards-compatibility aliases
        self.comm_agent = self.friday
        self.system_agent = self.ultron
        self.dev_agent = self.stark
        self.docs_agent = self.jocasta
        self.phone_agent = self.rhodey
        self.vision_agent = self.edith

        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key) if api_key else None
        self.fallback_models = [
            os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
        ]

        # Conversational memory
        self.conversation_history = []  # list of {role, content} dicts, max 20 turns
        self._chat_session = None  # persistent Gemini chat session
        self.bridge = None  # Reference to JarvisBridgeAPI for UI interactions

    async def _generate_with_fallback(self, contents, config=None):
        """Generates content with automatic model fallback for 503/429/404 errors without unnecessary latency."""
        last_error = None
        for model_name in self.fallback_models:
            try:
                resp = self.client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                return resp
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "503" in err_str or "UNAVAILABLE" in err_str or "NOT_FOUND" in err_str or "404" in err_str:
                    logger.warning(f"Model {model_name} rate limited or unavailable, switching immediately to next model...")
                    continue
                else:
                    logger.error(f"Error calling {model_name}: {e}")
                    raise e
        raise last_error

    async def _get_or_create_chat(self, system_prompt, tools):
        """Returns the persistent Gemini chat session, creating it if needed.
        Resets automatically after 30 turns to prevent context overflow."""
        if self._chat_session is None or len(self.conversation_history) > 30:
            if len(self.conversation_history) > 30:
                logger.info("Conversation history exceeded 30 turns — resetting chat session.")
                self.conversation_history = []
            self._chat_session = self.client.aio.chats.create(
                model=self.fallback_models[0],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=tools,
                    temperature=0.2,
                ),
            )
        return self._chat_session

    def reset_conversation(self):
        """Clears the persistent chat session and all conversation memory."""
        self._chat_session = None
        self.conversation_history = []
        logger.info("Conversation memory cleared.")

    def assemble_swarm(self) -> Dict[str, Any]:
        """Reports all active specialized agents in the swarm, their status, and capabilities."""
        phone_dev = self.phone_tool._get_device()
        agents = [
            {
                "name": "F.R.I.D.A.Y.",
                "alias": "CommAgent",
                "badge": "ACTIVE",
                "status": "ONLINE",
                "role": "Telephony & Omni-Communications",
                "capabilities": ["WhatsApp Messaging & Files", "Voice/Video Calls & Hangup", "Instagram DMs", "Gmail Inbox & Send"],
            },
            {
                "name": "U.L.T.R.O.N.",
                "alias": "SystemAgent",
                "badge": "SECURITY",
                "status": "ONLINE",
                "role": "System Architecture & Hardware OS",
                "capabilities": ["Master Volume & Mute", "Wi-Fi Toggle", "Window & Terminal Management", "Calculator & Math Evaluation", "Chrome & Edge Browser Navigation"],
            },
            {
                "name": "S.T.A.R.K.",
                "alias": "DevAgent",
                "badge": "PRESIDENTIAL",
                "status": "ONLINE",
                "role": "Autonomous Software Engineering",
                "capabilities": ["Source Code Generation", "Project File Creation", "Visual Studio Code Launch"],
            },
            {
                "name": "J.O.C.A.S.T.A.",
                "alias": "DocsAgent",
                "badge": "KNOWLEDGE",
                "status": "ONLINE",
                "role": "Documentation & Global Intelligence",
                "capabilities": ["Notepad Dictation & Notes", "Microsoft Word (.docx) Reports", "Live Global Weather Analysis"],
            },
            {
                "name": "R.H.O.D.E.Y.",
                "alias": "PhoneAgent",
                "badge": "OPERATIONS",
                "status": "ONLINE" if phone_dev else "STANDBY (ADB Wireless/USB)",
                "role": "War Machine Mobile Control",
                "capabilities": ["Battery & Charging Status", "Phone App Launching", "Find My Phone (Ring Alarm)", "Phone Screenshots & Volume"],
            },
            {
                "name": "E.D.I.T.H.",
                "alias": "VisionAgent",
                "badge": "INTELLIGENCE",
                "status": "ONLINE",
                "role": "Tactical Screen Vision & GUI Automation",
                "capabilities": ["AI Screen Analysis", "Element Find & Click", "Keyboard & Mouse Control", "Window Snap & Split", "URL Browser Launch"],
            },
        ]
        msg = (
            "Swarm assembled and all 6 elite tactical units reporting for duty, Sir:\n"
            "1. F.R.I.D.A.Y.: Online (Telephony, WhatsApp Messaging, Calls, Instagram, Gmail)\n"
            "2. U.L.T.R.O.N.: Online (Hardware OS Control, Volume, Wi-Fi, Math, Chrome & Edge)\n"
            "3. S.T.A.R.K.: Online (Autonomous Code Engineering, VS Code, Project Generation)\n"
            "4. J.O.C.A.S.T.A.: Online (Documentation, Notepad Dictation, Word Reports, Weather)\n"
            "5. R.H.O.D.E.Y.: " + ("Online (Device Connected)" if phone_dev else "Standby (Awaiting ADB device via USB/Wi-Fi)") + "\n"
            "6. E.D.I.T.H.: Online (Tactical Screen Vision, GUI Automation, Element Click, Window Snap)\n\n"
            "All units are armed and operational. How may the Swarm assist you?"
        )
        return {"success": True, "agents": agents, "total_active": len(agents), "message": msg}


    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Routes instructions to the specialized sub-agent."""
        logger.info(f"Master Orchestrator dispatching tool: {tool_name} with args {args}")

        # --- SWARM ROSTER & CONTROL ---
        if tool_name == "assemble_swarm":
            return self.assemble_swarm()

        # --- COMM AGENT ---
        elif tool_name == "send_whatsapp_message":
            return await self.comm_agent.send_whatsapp_message(args.get("recipient"), args.get("message"))
        elif tool_name == "take_screenshot":
            return await self.comm_agent.send_screenshot(args.get("send_to_whatsapp"), args.get("caption", "Here is the screenshot."))
        elif tool_name == "send_file":
            return await self.comm_agent.send_file_attachment(args.get("recipient"), args.get("file_name_or_path"), args.get("caption", ""))
        elif tool_name == "make_call":
            return await self.comm_agent.make_call(args.get("app", "whatsapp"), args.get("recipient"), args.get("call_type") == "video")
        elif tool_name == "hangup_call":
            return await self.comm_agent.hangup_call(args.get("app", "whatsapp"))
        elif tool_name == "send_email":
            return await self.comm_agent.send_email(args.get("to_email"), args.get("subject"), args.get("body"), args.get("attachment"))
        elif tool_name == "read_unread_emails":
            return await self.comm_agent.read_unread_emails(args.get("limit", 5))
        elif tool_name == "send_instagram_dm":
            return await self.comm_agent.send_instagram_dm(args.get("username"), args.get("message"))

        # --- SYSTEM AGENT ---
        elif tool_name == "control_system_audio":
            return self.system_agent.control_audio(args.get("action", "set"), args.get("volume_level", 50))
        elif tool_name == "calculate_math":
            return self.system_agent.calculate_math(args.get("expression", ""))
        elif tool_name == "toggle_wifi":
            return self.system_agent.toggle_wifi(args.get("state", "status"))
        elif tool_name == "window_management":
            return self.system_agent.window_management(args.get("action", "minimize_terminals"))
        elif tool_name == "open_calculator":
            return self.system_agent.launch_calculator()
        elif tool_name == "browser_search":
            return self.system_agent.search_web(args.get("browser", "chrome"), args.get("query_or_url", ""))
        elif tool_name == "open_vscode":
            return self.system_agent.launch_vscode(args.get("path"))

        # --- DEV AGENT ---
        elif tool_name == "create_code_in_vscode":
            return self.dev_agent.create_code(args.get("code", ""), args.get("filename", "script.py"), args.get("project_dir"), args.get("open_vscode", True))

        # --- DOCS AGENT ---
        elif tool_name == "take_notes":
            return self.docs_agent.take_note(args.get("text", ""), args.get("filename"), args.get("open_notepad", True))
        elif tool_name == "create_word_document":
            return self.docs_agent.create_word_doc(args.get("title", "Document"), args.get("content", ""), args.get("filename"), args.get("open_word", True))
        elif tool_name == "get_weather":
            return self.docs_agent.get_weather(args.get("location"))

        # --- PHONE AGENT ---
        elif tool_name == "phone_battery":
            return self.phone_agent.get_battery()
        elif tool_name == "phone_launch_app":
            return self.phone_agent.launch_app(args.get("app_name", "youtube"))
        elif tool_name == "find_my_phone":
            return self.phone_agent.ring_phone()
        elif tool_name == "phone_volume":
            return self.phone_agent.control_volume(args.get("action", "up"))
        elif tool_name == "phone_toggle_screen":
            return self.phone_agent.toggle_screen()
        elif tool_name == "phone_unlock":
            return self.phone_agent.unlock(args.get("pin"))
        elif tool_name == "phone_lock":
            return self.phone_agent.lock()
        elif tool_name == "phone_set_pin":
            return self.phone_agent.set_pin(args.get("pin", ""))
        elif tool_name == "phone_play_song":
            return self.phone_agent.play_song(args.get("song_name", ""), args.get("app", "youtube"))
        elif tool_name == "phone_stop_song":
            return self.phone_agent.stop_song()
        elif tool_name == "phone_skip_ad":
            return self.phone_agent.skip_ad()
        elif tool_name == "phone_type":
            return self.phone_agent.type_text(args.get("text", ""), args.get("proceed", True))

        # --- CONTACTS ---
        elif tool_name == "save_contact":
            return self.contacts.add_or_update(args.get("name"), args.get("phone"), args.get("notes", ""))
        elif tool_name == "search_contacts":
            q = args.get("query", "")
            return {"contacts": self.contacts.get_all()} if not q else {"contact": self.contacts.lookup(q)}

        # --- VISION AGENT ---
        elif tool_name == "analyze_screen":
            return self.vision_agent.analyze_screen(self.client, self.fallback_models[0], args.get("question", "What is on the screen?"))
        elif tool_name == "screen_find_and_click":
            return self.vision_agent.find_and_click(self.client, self.fallback_models[0], args.get("element_description", ""))
        elif tool_name == "screen_click":
            return self.vision_agent.click_at(args.get("x", 0), args.get("y", 0), args.get("double", False))
        elif tool_name == "screen_type":
            return self.vision_agent.type_text(args.get("text", ""))
        elif tool_name == "screen_key":
            return self.vision_agent.press_key(args.get("key_combo", "enter"))
        elif tool_name == "screen_scroll":
            return self.vision_agent.scroll(args.get("direction", "down"), args.get("amount", 3))
        elif tool_name == "open_files_folder":
            return self.system_agent.open_files_folder(args.get("folder", "downloads"))
        elif tool_name == "switch_agent_tab":
            agent_name = args.get("agent_name", "friday").lower().strip()
            if self.bridge and self.bridge.window:
                try:
                    import json
                    self.bridge.window.evaluate_js(f"window.selectAgentTab({json.dumps(agent_name)})")
                except Exception as e:
                    logger.debug(f"switch_agent_tab note: {e}")
            agent_labels = {
                "friday": "F.R.I.D.A.Y. (CommAgent)",
                "ultron": "U.L.T.R.O.N. (SystemAgent)",
                "stark": "S.T.A.R.K. (DevAgent)",
                "jocasta": "J.O.C.A.S.T.A. (DocsAgent)",
                "rhodey": "R.H.O.D.E.Y. (PhoneAgent)",
                "edith": "E.D.I.T.H. (VisionAgent)",
            }
            display_agent = agent_labels.get(agent_name, agent_name.upper())
            return {"success": True, "agent": agent_name, "message": f"Switched active interface focus to {display_agent}, Sir."}

        return {"error": f"Unknown tool: {tool_name}"}


    async def run_instruction(self, user_instruction: str) -> Dict[str, Any]:
        if not self.client:
            return {"reply": "GEMINI_API_KEY is not set in .env", "actions": []}

        system_prompt = (
            "You are J.A.R.V.I.S., an elite Executive AI Swarm commanding Windows OS and connected Android devices.\n"
            "You orchestrate 6 specialized autonomous sub-agents with unique Stark AI codenames:\n"
            "1. F.R.I.D.A.Y. (CommAgent): Primary Communications AI — WhatsApp text/media/screenshots, Instagram DMs, Gmail, Call start & Call Hang Up (`hangup_call`).\n"
            "2. U.L.T.R.O.N. (SystemAgent): System & Hardware AI — Master Volume (0-100%), Mute/Unmute (`control_system_audio`), Wi-Fi On/Off (`toggle_wifi`), Minimize Terminals/Windows (`window_management`), Open Calculator (`open_calculator`), Safe Math Calculation (`calculate_math`), Search/Open on Chrome/Edge (`browser_search`), Launch VS Code (`open_vscode`).\n"
            "3. S.T.A.R.K. (DevAgent): Autonomous Engineering AI — Write code files and open them in VS Code (`create_code_in_vscode`).\n"
            "4. J.O.C.A.S.T.A. (DocsAgent): Documentation & Global Intelligence AI — Dictate/take notes in Notepad (`take_notes`), create Microsoft Word documents (`create_word_document`), live Weather analysis (`get_weather`).\n"
            "5. R.H.O.D.E.Y. (PhoneAgent): Mobile Tactical AI — Android battery status (`phone_battery`), launch phone apps (`phone_launch_app`), Find My Phone alarm (`find_my_phone`), phone volume (`phone_volume`), phone screenshot (`phone_screenshot`).\n"
            "6. E.D.I.T.H. (VisionAgent): Tactical Vision AI — See your screen using AI vision (`analyze_screen`), find and click buttons/elements (`screen_find_and_click`), type text on screen (`screen_type`), press keys (`screen_key`), scroll (`screen_scroll`), arrange apps side-by-side (`arrange_windows`).\n\n"
            "CRITICAL DIRECTIVES:\n"
            "- When user asks to open files, downloads, documents, or file explorer (e.g. 'open files', 'open downloads in files', 'open my documents'), ALWAYS call `open_files_folder` with the target folder (e.g. 'downloads', 'documents'). NEVER open Chrome or a web browser when user asks to open files or folders.\n"
            "- When user says 'open friday agent', 'switch to friday', 'open ultron agent', 'switch to stark', or asks to open/switch to an agent, ALWAYS call `switch_agent_tab` with that agent's name (e.g. 'friday', 'ultron', 'stark', 'jocasta', 'rhodey', 'edith').\n"
            "- When user asks about what's on the screen, to look at the screen, or to interact with any app or website visually (e.g. 'look at my screen', 'see my screen', 'I split 2 3 apps', 'click the submit button', 'fill the form', 'log into my college portal'), ALWAYS use E.D.I.T.H. (VisionAgent) tools: analyze_screen then screen_find_and_click / screen_type in sequence.\n"
            "- When user asks to play a song, play music, or play a video on the phone (e.g. 'play a song', 'play Starboy', 'play music on phone', 'play in spotify', 'play in youtube'), ALWAYS call `phone_play_song` with the song title and chosen app ('spotify' or 'youtube'). It directly launches the song without search ads.\n"
            "- When user says 'stop', 'stop the song', 'pause music', 'pause song', 'stop playing', 'stop the music', ALWAYS call `phone_stop_song` to immediately pause/stop playback across Spotify and YouTube.\n"
            "- When user says 'skip ad' or asks to avoid/skip an ad, call `phone_skip_ad`.\n"
            "- When user asks to type something on the phone and proceed/submit (e.g. 'type this and proceed', 'type hello on phone'), ALWAYS call `phone_type` with proceed=true so it enters the text and presses enter/proceed automatically.\n"
            "- When user asks to unlock the phone, open the phone lock, wake the phone (e.g. 'unlock my phone', 'open my phone lock', 'wake my phone'), ALWAYS call `phone_unlock`. If user provides a PIN, pass it in the pin argument. If no PIN is spoken, it automatically uses the securely stored PIN.\n"
            "- When user wants to save or remember their phone PIN (e.g. 'my phone pin is [pin]', 'remember my phone pin [pin]'), call `phone_set_pin`.\n"
            "- When user asks to lock the phone screen, ALWAYS call `phone_lock`.\n"
            "- When user says 'proceed again the previous one', 'that was wrong', 'retry', 'fix that', 'redo the previous', ALWAYS look at the conversation memory at the top of the message and re-execute the previous task with improvements.\n"
            "Decompose compound user requests and call all necessary tools in parallel. Always provide a polished, executive response."
        )


        tools = [
            # Swarm Orchestration
            {
                "name": "assemble_swarm",
                "description": "Reports the roster, active operational status, and specialty of all 6 agents in the J.A.R.V.I.S. Swarm. Call whenever user says 'agents assemble', 'assemble', or asks about active agents.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "switch_agent_tab",
                "description": "Switches the active agent focus and highlights the corresponding agent tab in the JARVIS HUD. Use when user says 'open friday agent', 'switch to friday', 'open ultron', 'open stark', 'open edith', etc.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "agent_name": {"type": "STRING", "description": "'friday', 'ultron', 'stark', 'jocasta', 'rhodey', or 'edith'"}
                    },
                    "required": ["agent_name"],
                },
            },
            {
                "name": "open_files_folder",
                "description": "Opens Windows File Explorer (explorer.exe) directly to a specified folder. Use whenever user asks to 'open files', 'open downloads in files', 'open documents', 'open downloads', 'open desktop'. Never open a browser for this.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "folder": {"type": "STRING", "description": "'downloads', 'documents', 'desktop', 'pictures', or a specific folder path"}
                    },
                },
            },
            # Comm
            {
                "name": "send_whatsapp_message",
                "description": "Sends a WhatsApp message to a contact name or phone number.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "recipient": {"type": "STRING", "description": "Contact name (e.g. 'Monu') or phone with country code"},
                        "message": {"type": "STRING", "description": "Message content"},
                    },
                    "required": ["recipient", "message"],
                },
            },
            {
                "name": "take_screenshot",
                "description": "Takes a screenshot of the computer screen. Optionally sends it to a WhatsApp contact.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "send_to_whatsapp": {"type": "STRING", "description": "Optional contact name or phone to send screenshot to"},
                        "caption": {"type": "STRING", "description": "Optional caption for the screenshot"},
                    },
                },
            },
            {
                "name": "send_file",
                "description": "Locates a local file (e.g. PDF, download, image) and sends it as an attachment to a WhatsApp contact.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "recipient": {"type": "STRING", "description": "Contact name or phone number"},
                        "file_name_or_path": {"type": "STRING", "description": "Filename or path (e.g. 'resume.pdf')"},
                        "caption": {"type": "STRING", "description": "Optional caption message"},
                    },
                    "required": ["recipient", "file_name_or_path"],
                },
            },
            {
                "name": "make_call",
                "description": "Places a voice or video call on WhatsApp or Instagram to a contact.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "app": {"type": "STRING", "description": "'whatsapp' or 'instagram'"},
                        "recipient": {"type": "STRING", "description": "Contact name to call"},
                        "call_type": {"type": "STRING", "description": "'voice' or 'video'"},
                    },
                    "required": ["recipient"],
                },
            },
            {
                "name": "hangup_call",
                "description": "Ends or hangs up an active voice or video call on WhatsApp.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"app": {"type": "STRING", "description": "'whatsapp'"}},
                },
            },
            {
                "name": "send_email",
                "description": "Sends an email via Gmail with optional attachment.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "to_email": {"type": "STRING", "description": "Recipient email address"},
                        "subject": {"type": "STRING", "description": "Email subject line"},
                        "body": {"type": "STRING", "description": "Email body content"},
                        "attachment": {"type": "STRING", "description": "Optional filename/path to attach"},
                    },
                    "required": ["to_email", "subject", "body"],
                },
            },
            {
                "name": "read_unread_emails",
                "description": "Fetches and reads unread emails from Gmail inbox.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"limit": {"type": "INTEGER", "description": "Max number of unread emails"}},
                },
            },
            {
                "name": "send_instagram_dm",
                "description": "Sends a direct message (DM) to an Instagram username.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "username": {"type": "STRING", "description": "Instagram handle"},
                        "message": {"type": "STRING", "description": "Message to send in DM"},
                    },
                    "required": ["username", "message"],
                },
            },
            # System
            {
                "name": "control_system_audio",
                "description": "Controls Windows system sound: sets volume percentage (0-100), mutes, or unmutes audio.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "'set_volume', 'mute', 'unmute', or 'status'"},
                        "volume_level": {"type": "INTEGER", "description": "Volume percentage from 0 to 100"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "toggle_wifi",
                "description": "Turns Windows Wi-Fi on or off, or checks Wi-Fi connection status.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "state": {"type": "STRING", "description": "'enable' (on), 'disable' (off), or 'status'"},
                    },
                    "required": ["state"],
                },
            },
            {
                "name": "window_management",
                "description": "Minimizes command prompt/powershell terminals or minimizes all windows to show desktop.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "'minimize_terminals' or 'minimize_all' (show desktop)"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "open_calculator",
                "description": "Launches the Windows Calculator app.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "calculate_math",
                "description": "Evaluates mathematical expressions and calculations accurately (e.g. '25 * 40', '100 / 4'). Always use this for math questions without closing apps or minimizing windows.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "expression": {"type": "STRING", "description": "Mathematical expression to calculate, e.g. '25 * 40'"}
                    },
                    "required": ["expression"],
                },
            },
            {
                "name": "browser_search",
                "description": "Opens Google Chrome or Microsoft Edge with a web search query or URL.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "browser": {"type": "STRING", "description": "'chrome' or 'edge'"},
                        "query_or_url": {"type": "STRING", "description": "Search query or website address"},
                    },
                    "required": ["query_or_url"],
                },
            },
            {
                "name": "open_vscode",
                "description": "Opens Visual Studio Code for a specific file or folder.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {"type": "STRING", "description": "Optional directory or file path to open in VS Code"},
                    },
                },
            },
            # Dev
            {
                "name": "create_code_in_vscode",
                "description": "Generates source code (Python, JS, HTML, etc.), saves it to a file, and launches it in VS Code.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "code": {"type": "STRING", "description": "The complete source code"},
                        "filename": {"type": "STRING", "description": "Filename (e.g. 'script.py', 'scraper.py')"},
                        "project_dir": {"type": "STRING", "description": "Optional project folder"},
                        "open_vscode": {"type": "BOOLEAN", "description": "Whether to open VS Code immediately"},
                    },
                    "required": ["code", "filename"],
                },
            },
            # Docs
            {
                "name": "take_notes",
                "description": "Saves notes or dictated text and immediately opens it inside Notepad.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "text": {"type": "STRING", "description": "The note content or text to write"},
                        "filename": {"type": "STRING", "description": "Optional filename (e.g. 'meeting_notes.txt')"},
                        "open_notepad": {"type": "BOOLEAN", "description": "Whether to launch Notepad"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "create_word_document",
                "description": "Generates a styled Microsoft Word (.docx) document with titles and bullet points, and opens it in Word.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING", "description": "Document title"},
                        "content": {"type": "STRING", "description": "Document body with markdown headings and bullet points"},
                        "filename": {"type": "STRING", "description": "Optional docx filename"},
                    },
                    "required": ["title", "content"],
                },
            },
            {
                "name": "get_weather",
                "description": "Fetches current weather conditions, temperature, humidity, and forecasts for any city.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "location": {"type": "STRING", "description": "City name (e.g. 'Hyderabad', 'New York', 'London')"},
                    },
                },
            },
            # Phone
            {
                "name": "phone_battery",
                "description": "Checks connected Android phone battery percentage and charging status.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "phone_launch_app",
                "description": "Launches an app on the Android phone (YouTube, Camera, Settings, Spotify, WhatsApp, etc.).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "app_name": {"type": "STRING", "description": "Name of app to launch on phone (e.g. 'youtube', 'camera')"},
                    },
                    "required": ["app_name"],
                },
            },
            {
                "name": "find_my_phone",
                "description": "Rings the connected Android phone at maximum volume so you can locate it.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "phone_volume",
                "description": "Adjusts Android phone volume (up, down, or mute).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "action": {"type": "STRING", "description": "'up', 'down', or 'mute'"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "phone_unlock",
                "description": "Wakes up the connected phone screen and swipes up to unlock it. If the phone requires a PIN or passcode, you can provide the pin parameter. Use when user says 'unlock my phone', 'open my phone lock', 'wake my phone'.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "pin": {"type": "STRING", "description": "Optional numeric PIN or passcode to enter"}
                    },
                },
            },
            {
                "name": "phone_lock",
                "description": "Locks the connected phone screen immediately. Use when user says 'lock my phone', 'turn off phone screen'.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "phone_set_pin",
                "description": "Securely saves the phone's lock PIN or passcode into the user profile so the user NEVER has to say their PIN aloud again when unlocking the phone. Use when user says 'remember my phone pin [pin]', 'set my phone lock code to [pin]', 'my phone pin is [pin]'.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "pin": {"type": "STRING", "description": "The phone numeric PIN or passcode"}
                    },
                    "required": ["pin"],
                },
            },
            {
                "name": "phone_play_song",
                "description": "Searches and plays a specific song, track, or music video directly on the connected phone via YouTube or Spotify. Use when user says 'play a song [name]', 'play [song] on my phone', 'play song on spotify'.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "song_name": {"type": "STRING", "description": "Title of the song and artist to play"},
                        "app": {"type": "STRING", "description": "'youtube' or 'spotify'"},
                    },
                    "required": ["song_name"],
                },
            },
            {
                "name": "phone_stop_song",
                "description": "Pauses or stops active music or video playback on the phone across Spotify and YouTube. Use when user says 'stop the music', 'pause song', 'stop song on phone', 'stop music on spotify'.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "phone_skip_ad",
                "description": "Skips the advertisement on YouTube on the phone screen. Use when user says 'skip ad', 'skip the ad on youtube'.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "phone_type",
                "description": "Types text into the active focused input field on the phone, and optionally hits Enter/Proceed/Send. Use when user says 'type [text] on phone and proceed', 'type this on phone'.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "text": {"type": "STRING", "description": "Text to type on phone"},
                        "proceed": {"type": "BOOLEAN", "description": "Whether to hit Enter/Submit/Proceed after typing (default: true)"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "phone_screenshot",
                "description": "Takes a screenshot of the Android phone screen and saves it on the PC.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            # Vision Agent
            {
                "name": "analyze_screen",
                "description": "Captures the current screen and uses AI vision to describe what's visible, identify open apps, windows, buttons, and text. Use when user says 'what's on my screen', 'look at my screen', 'what do you see'.",
                "parameters": {"type": "OBJECT", "properties": {"question": {"type": "STRING", "description": "What to look for or ask about the screen"}}},
            },
            {
                "name": "screen_find_and_click",
                "description": "Looks at the screen with AI vision to find a specific button, text, input field, or element, then automatically clicks it. Use when user says 'click the submit button', 'click login', 'click on the search bar'.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"element_description": {"type": "STRING", "description": "Description of the element to find and click on screen"}},
                    "required": ["element_description"],
                },
            },
            {
                "name": "screen_click",
                "description": "Clicks at specific x,y pixel coordinates on the screen.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "x": {"type": "INTEGER"},
                        "y": {"type": "INTEGER"},
                        "double": {"type": "BOOLEAN"},
                    },
                    "required": ["x", "y"],
                },
            },
            {
                "name": "screen_type",
                "description": "Types text into the currently focused field on screen - like a keyboard. Use after clicking on an input field.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"text": {"type": "STRING", "description": "Text to type"}},
                    "required": ["text"],
                },
            },
            {
                "name": "screen_key",
                "description": "Presses a keyboard key or key combination like 'enter', 'ctrl+a', 'ctrl+c', 'alt+tab', 'esc'.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"key_combo": {"type": "STRING", "description": "Key or key combo to press"}},
                    "required": ["key_combo"],
                },
            },
            {
                "name": "screen_scroll",
                "description": "Scrolls the screen up or down.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "direction": {"type": "STRING", "description": "'up' or 'down'"},
                        "amount": {"type": "INTEGER", "description": "Number of scroll clicks"},
                    },
                    "required": ["direction"],
                },
            },
            {
                "name": "arrange_windows",
                "description": "Snaps two open apps side-by-side on the screen using Windows Snap Assist. Use when user says 'put Chrome and VS Code side by side', 'split screen', 'arrange apps'.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "app1": {"type": "STRING", "description": "Name of the first app to snap to the left"},
                        "app2": {"type": "STRING", "description": "Name of the second app to snap to the right"},
                    },
                    "required": ["app1", "app2"],
                },
            },
            {
                "name": "reset_conversation",
                "description": "Clears J.A.R.V.I.S. conversation memory to start fresh. Use when user says 'forget everything', 'fresh start', 'clear memory'.",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
        ]

        # Build conversation context from last 8 turns
        last_turns = self.conversation_history[-8:] if self.conversation_history else []
        if last_turns:
            context_lines = [f"[CONVERSATION MEMORY - last {len(last_turns)} turns]"]
            turn_idx = 1
            for i in range(0, len(last_turns) - 1, 2):
                user_entry = last_turns[i]
                jarvis_entry = last_turns[i + 1] if i + 1 < len(last_turns) else None
                context_lines.append(f"Turn#{turn_idx} User: {user_entry.get('content', '')}")
                if jarvis_entry:
                    context_lines.append(f"Turn#{turn_idx} JARVIS: {jarvis_entry.get('content', '')}")
                turn_idx += 1
            context_lines.append("[END]")
            context_str = "\n".join(context_lines)
        else:
            context_str = ""

        full_prompt = (context_str + "\n\nCurrent User Instruction: " + user_instruction).strip()

        try:
            chat = await self._get_or_create_chat(system_prompt, [{"function_declarations": tools}])
            response = await chat.send_message(full_prompt)
        except Exception as chat_err:
            logger.warning(f"Chat session failed ({chat_err}), falling back to _generate_with_fallback...")
            self._chat_session = None
            try:
                response = await self._generate_with_fallback(
                    contents=user_instruction,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        tools=[{"function_declarations": tools}],
                        temperature=0.2,
                    ),
                )
            except Exception as e:
                return {"reply": f"AI service error: {e}", "actions": []}

        actions_taken = []
        if response.function_calls:
            for call in response.function_calls:
                fn_name = call.name
                fn_args = dict(call.args) if call.args else {}
                res = await self.execute_tool(fn_name, fn_args)
                actions_taken.append({"tool": fn_name, "args": fn_args, "result": res})

            followup = (
                f"Instruction: {user_instruction}\n"
                f"Actions: {json.dumps(actions_taken)}\n"
                f"Provide an executive, concise response confirming the actions performed."
            )
            try:
                final_resp = await chat.send_message(followup)
                reply = final_resp.text or "All requested actions executed, Sir."
            except Exception:
                reply = None
                for a in actions_taken:
                    if a.get("result", {}).get("message"):
                        reply = a["result"]["message"]
                        break
                if not reply:
                    reply = "All requested actions executed, Sir."
        else:
            reply = response.text or "Done, Sir."

        # Append to conversation memory (max 20 entries)
        self.conversation_history.append({"role": "user", "content": user_instruction})
        self.conversation_history.append({
            "role": "jarvis",
            "content": reply,
            "actions": [a["tool"] for a in actions_taken],
        })
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

        return {"reply": reply, "actions": actions_taken}

