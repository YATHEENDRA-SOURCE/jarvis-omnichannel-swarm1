import os
import re
import subprocess
import logging
import urllib.parse
import win32gui
import win32con
import win32process
from typing import Dict, Any, Optional

logger = logging.getLogger("system_os_tool")

# Verified absolute paths for browsers on Windows
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_PATH_X86 = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
EDGE_PATH_64 = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"

POPULAR_SITES = {
    "chatgpt": "https://chatgpt.com",
    "gpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "google": "https://www.google.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "netflix": "https://www.netflix.com",
    "gmail": "https://mail.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
}


class SystemOSTool:
    """Controls Windows hardware, audio volume, Wi-Fi, window management, math calculations, and application launching."""

    def __init__(self):
        pass

    # ==================== AUDIO / VOLUME CONTROLS ====================

    def _get_audio_endpoint(self):
        """Initializes pycaw audio endpoint volume."""
        try:
            from pycaw.pycaw import AudioUtilities
            spk = AudioUtilities.GetSpeakers()
            if spk and hasattr(spk, "EndpointVolume"):
                return spk.EndpointVolume
        except Exception as e:
            logger.debug(f"pycaw modern endpoint error: {e}")

        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            from ctypes import cast, POINTER
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            return volume
        except Exception as e:
            logger.error(f"pycaw audio endpoint error: {e}")
            return None

    def set_volume(self, level: int) -> Dict[str, Any]:
        """Sets master system volume from 0 to 100%."""
        level = max(0, min(100, int(level)))
        scalar = level / 100.0

        endpoint = self._get_audio_endpoint()
        if endpoint:
            try:
                endpoint.SetMasterVolumeLevelScalar(scalar, None)
                if level > 0 and endpoint.GetMute():
                    endpoint.SetMute(0, None)
                logger.info(f"System volume set to {level}%")
                return {"success": True, "volume": level, "message": f"System volume set to {level}%"}
            except Exception as e:
                logger.error(f"Failed to set volume: {e}")

        # Fallback using PowerShell
        try:
            cmd = f"$obj = New-Object -ComObject WScript.Shell; 1..50 | % {{ $obj.SendKeys([char]174) }}; 1..{level//2} | % {{ $obj.SendKeys([char]175) }}"
            subprocess.run(["powershell", "-Command", cmd], check=False, stdout=subprocess.DEVNULL)
            return {"success": True, "volume": level, "message": f"Volume adjusted to {level}%"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def mute_sound(self, mute: bool = True) -> Dict[str, Any]:
        """Mutes or unmutes master system audio."""
        endpoint = self._get_audio_endpoint()
        if endpoint:
            try:
                endpoint.SetMute(1 if mute else 0, None)
                state_str = "muted" if mute else "unmuted"
                logger.info(f"System sound {state_str}")
                return {"success": True, "muted": mute, "message": f"System sound {state_str}."}
            except Exception as e:
                logger.error(f"Mute sound error: {e}")

        # Fallback: Send mute key
        try:
            subprocess.run(
                ["powershell", "-Command", "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"],
                check=False,
                stdout=subprocess.DEVNULL,
            )
            state_str = "muted" if mute else "unmuted"
            return {"success": True, "muted": mute, "message": f"Sound {state_str}."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_volume_status(self) -> Dict[str, Any]:
        """Returns current volume percentage and mute status."""
        endpoint = self._get_audio_endpoint()
        if endpoint:
            try:
                scalar = endpoint.GetMasterVolumeLevelScalar()
                is_muted = bool(endpoint.GetMute())
                pct = int(round(scalar * 100))
                return {"success": True, "volume": pct, "muted": is_muted}
            except Exception as e:
                logger.error(f"Get volume error: {e}")
        return {"success": False, "volume": 50, "muted": False}

    # ==================== WI-FI CONTROLS ====================

    def toggle_wifi(self, state: str) -> Dict[str, Any]:
        """Enables, disables, or checks Wi-Fi interface status."""
        action = state.lower().strip()
        if action in ("on", "enable", "enabled", "connect"):
            cmd = 'netsh interface set interface name="Wi-Fi" admin=ENABLE'
            msg = "Wi-Fi turned ON."
        elif action in ("off", "disable", "disabled", "disconnect"):
            cmd = 'netsh interface set interface name="Wi-Fi" admin=DISABLE'
            msg = "Wi-Fi turned OFF."
        else:
            try:
                res = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, check=False)
                return {"success": True, "status": res.stdout, "message": "Wi-Fi interface status retrieved."}
            except Exception as e:
                return {"success": False, "error": str(e)}

        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                logger.info(msg)
                return {"success": True, "message": msg}
            else:
                err = proc.stderr.strip() or proc.stdout.strip()
                if "elevation" in err.lower() or "administrator" in err.lower():
                    return {"success": False, "error": "Administrator privileges required to toggle Wi-Fi adapter. Please run JARVIS as Administrator."}
                return {"success": False, "error": err or "Wi-Fi toggle failed."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== WINDOW & TERMINAL MANAGEMENT ====================

    def minimize_terminals(self) -> Dict[str, Any]:
        """Finds and minimizes ONLY command prompt / powershell / terminal windows without closing user applications."""
        minimized_count = 0
        terminal_exes = ["cmd.exe", "powershell.exe", "windowsterminal.exe", "pwsh.exe", "mintty.exe", "bash.exe"]

        def enum_windows_callback(hwnd, extra):
            nonlocal minimized_count
            if win32gui.IsWindowVisible(hwnd):
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    import psutil
                    proc = psutil.Process(pid)
                    pname = proc.name().lower()
                    if pname in terminal_exes:
                        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                        minimized_count += 1
                except Exception:
                    pass
            return True

        try:
            win32gui.EnumWindows(enum_windows_callback, None)
            logger.info(f"Minimized {minimized_count} terminal window(s).")
            return {"success": True, "count": minimized_count, "message": f"Minimized {minimized_count} terminal window(s)."}
        except Exception as e:
            logger.error(f"Minimize terminals error: {e}")
            return {"success": False, "error": str(e)}

    def minimize_all_windows(self) -> Dict[str, Any]:
        """Minimizes all windows to show desktop (Win + D)."""
        try:
            cmd = "(New-Object -ComObject Shell.Application).MinimizeAll()"
            subprocess.run(["powershell", "-Command", cmd], check=False, stdout=subprocess.DEVNULL)
            logger.info("All windows minimized to desktop.")
            return {"success": True, "message": "All windows minimized to desktop, Sir."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== APP LAUNCHERS & MATH CALCULATIONS ====================

    def open_files_folder(self, folder: str = "downloads") -> Dict[str, Any]:
        """Launches Windows File Explorer (explorer.exe) directly to a specified folder.
        Supports: 'downloads', 'documents', 'desktop', 'pictures', 'videos', 'files', or custom path."""
        user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        f_lower = (folder or "downloads").lower().strip()

        folder_map = {
            "downloads": os.path.join(user_profile, "Downloads"),
            "download": os.path.join(user_profile, "Downloads"),
            "documents": os.path.join(user_profile, "Documents"),
            "document": os.path.join(user_profile, "Documents"),
            "desktop": os.path.join(user_profile, "Desktop"),
            "pictures": os.path.join(user_profile, "Pictures"),
            "photos": os.path.join(user_profile, "Pictures"),
            "videos": os.path.join(user_profile, "Videos"),
            "music": os.path.join(user_profile, "Music"),
            "files": os.path.join(user_profile, "Downloads"),
            "file": os.path.join(user_profile, "Downloads"),
            "my files": os.path.join(user_profile, "Downloads"),
            "home": user_profile,
            "root": user_profile,
            "this pc": "",
        }

        # Check mapped shortcuts
        target_path = folder_map.get(f_lower, None)
        if target_path is None:
            # Check if direct absolute or relative directory
            if os.path.exists(folder):
                target_path = os.path.abspath(folder)
            else:
                # Default fallback
                target_path = os.path.join(user_profile, "Downloads")

        try:
            if target_path:
                subprocess.Popen(["explorer.exe", target_path])
                display_name = os.path.basename(target_path) or target_path
                logger.info(f"Opened File Explorer at: {target_path}")
                return {
                    "success": True,
                    "folder": target_path,
                    "message": f"Opened {display_name} in File Explorer, Sir."
                }
            else:
                subprocess.Popen(["explorer.exe"])
                return {"success": True, "folder": "This PC", "message": "Opened File Explorer, Sir."}
        except Exception as e:
            logger.error(f"Error opening file explorer: {e}")
            return {"success": False, "error": str(e)}

    def open_calculator(self) -> Dict[str, Any]:
        """Launches the Windows Calculator app."""
        try:
            # Using start calculator: protocol or calc.exe
            subprocess.Popen(["calc.exe"], shell=True)
            logger.info("Calculator launched.")
            return {"success": True, "message": "Calculator is open, Sir."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def calculate_math(self, expression: str) -> Dict[str, Any]:
        """Evaluates mathematical calculations and expressions accurately."""
        clean_expr = expression.strip().lower()
        clean_expr = clean_expr.replace("x", "*").replace("times", "*").replace("divided by", "/").replace("plus", "+").replace("minus", "-")
        clean_expr = re.sub(r"[^\d\+\-\*\/\.\(\)\%\^ ]", "", clean_expr)

        try:
            # Safe evaluation
            result = eval(clean_expr, {"__builtins__": None}, {})
            msg = f"Calculation: {expression} = {result}"
            logger.info(msg)
            return {"success": True, "expression": expression, "result": result, "message": f"The answer to {expression} is {result}."}
        except Exception as e:
            return {"success": False, "error": f"Could not evaluate expression: {e}"}

    def browser_search(self, browser: str, query_or_url: str) -> Dict[str, Any]:
        """Opens Google Chrome or Microsoft Edge with a specific URL or web search."""
        b = browser.lower().strip()
        q = query_or_url.strip()
        q_lower = q.lower()

        # Intercept accidental browser searches for local folders/files
        if q_lower in ["open files", "files", "my files", "open downloads", "downloads", "open downloads in files", "downloads in files", "open documents", "documents", "open desktop", "desktop"]:
            folder_target = "downloads" if "download" in q_lower or "files" in q_lower else ("documents" if "document" in q_lower else "desktop")
            return self.open_files_folder(folder=folder_target)

        # Check if direct popular site
        if q_lower in POPULAR_SITES:
            target_url = POPULAR_SITES[q_lower]
        elif q.startswith("http://") or q.startswith("https://"):
            target_url = q
        elif any(q_lower.startswith(prefix) for prefix in ["open chatgpt", "open gpt", "chatgpt", "chat gpt"]):
            target_url = "https://chatgpt.com"
        elif any(q_lower.startswith(prefix) for prefix in ["open youtube", "youtube"]):
            target_url = "https://www.youtube.com"
        else:
            encoded = urllib.parse.quote(q)
            target_url = f"https://www.google.com/search?q={encoded}" if "chrome" in b else f"https://www.bing.com/search?q={encoded}"

        # Determine browser binary path
        exe_path = None
        if "edge" in b:
            if os.path.exists(EDGE_PATH):
                exe_path = EDGE_PATH
            elif os.path.exists(EDGE_PATH_64):
                exe_path = EDGE_PATH_64
            browser_name = "Microsoft Edge"
        else:
            if os.path.exists(CHROME_PATH):
                exe_path = CHROME_PATH
            elif os.path.exists(CHROME_PATH_X86):
                exe_path = CHROME_PATH_X86
            browser_name = "Google Chrome"

        logger.info(f"Launching {browser_name} with URL: {target_url}")
        try:
            if exe_path:
                subprocess.Popen([exe_path, target_url])
            else:
                # Windows Shell start
                os.startfile(target_url)

            return {
                "success": True,
                "browser": browser_name,
                "query": q,
                "url": target_url,
                "message": f"Opened {browser_name} with {target_url}, Sir.",
            }
        except Exception as e:
            logger.error(f"Browser launch error: {e}")
            import webbrowser
            webbrowser.open(target_url)
            return {"success": True, "browser": browser_name, "url": target_url, "message": f"Opened {target_url} in browser."}

    def _get_vscode_cmd(self) -> str:
        """Finds the best command or binary path for VS Code."""
        user_bin = os.path.expanduser(r"~\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd")
        user_exe = os.path.expanduser(r"~\AppData\Local\Programs\Microsoft VS Code\Code.exe")
        prog_cmd = r"C:\Program Files\Microsoft VS Code\bin\code.cmd"
        for p in [user_bin, user_exe, prog_cmd]:
            if os.path.exists(p):
                return p
        import shutil
        return shutil.which("code") or "code"

    def open_vscode(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Launches Visual Studio Code for a specific file, directory, or current workspace."""
        target_path = os.path.abspath(path) if path else os.getcwd()
        vscode_cmd = self._get_vscode_cmd()
        try:
            subprocess.Popen([vscode_cmd, target_path], shell=True)
            logger.info(f"VS Code opened for: {target_path} using {vscode_cmd}")
            return {"success": True, "path": target_path, "message": f"VS Code opened at {target_path}, Sir."}
        except Exception as e:
            logger.error(f"Failed to open VS Code: {e}")
            try:
                subprocess.Popen(["code", target_path], shell=True)
                return {"success": True, "path": target_path, "message": f"VS Code launched, Sir."}
            except Exception as e2:
                return {"success": False, "error": f"Could not launch VS Code: {e2}"}
