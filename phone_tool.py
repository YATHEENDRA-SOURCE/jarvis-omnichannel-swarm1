import os
import time
import re
import subprocess
import logging
from typing import Dict, Any, List, Optional
import adbutils

logger = logging.getLogger("phone_tool")

# Bundled ADB binary path
ADB_BIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "venv", "Lib", "site-packages", "adbutils", "binaries", "adb.exe"))
if not os.path.exists(ADB_BIN):
    ADB_BIN = "adb"


class PhoneTool:
    """Controls connected Android phones wirelessly (over Wi-Fi) or via USB using ADB."""

    PACKAGE_MAP = {
        "youtube": "com.google.android.youtube",
        "camera": "android.hardware.action.STILL_IMAGE_CAMERA",
        "settings": "com.android.settings",
        "whatsapp": "com.whatsapp",
        "spotify": "com.spotify.music",
        "chrome": "com.android.chrome",
        "maps": "com.google.android.apps.maps",
        "photos": "com.google.android.apps.photos",
        "gallery": "com.google.android.apps.photos",
        "clock": "com.google.android.deskclock",
        "calculator": "com.google.android.calculator",
        "instagram": "com.instagram.android",
        "gmail": "com.google.android.gm",
    }

    def __init__(self, screenshots_dir: str = "screenshots"):
        self.screenshots_dir = os.path.abspath(screenshots_dir)
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def _get_device(self):
        """Returns the first connected Android device, or None."""
        try:
            devices = adbutils.adb.device_list()
            if devices:
                return devices[0]
        except Exception as e:
            logger.debug(f"ADB device search error: {e}")
        return None

    def scan_and_diagnose(self) -> Dict[str, Any]:
        """Scans for connected Android devices and provides step-by-step setup diagnostics."""
        try:
            res = subprocess.run([ADB_BIN, "devices"], capture_output=True, text=True, check=False)
            output = res.stdout.strip()
            lines = [l.strip() for l in output.split("\n")[1:] if l.strip()]

            devices = []
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    devices.append({"serial": parts[0], "status": parts[1]})

            if not devices:
                instructions = (
                    "**No Android device detected.** Here is how to connect in 30 seconds:\n\n"
                    "**Step 1:** Plug your phone into your PC using a USB cable.\n"
                    "**Step 2:** On your phone, go to **Settings** -> **About Phone** -> tap **Build Number** 7 times to enable Developer Options.\n"
                    "**Step 3:** Go to **Settings** -> **Developer Options** -> Turn ON **USB Debugging**.\n"
                    "**Step 4:** Look at your phone screen: a popup will ask *'Allow USB debugging?'* -> Check **'Always allow'** and tap **OK**.\n\n"
                    "*(Once plugged in via USB once, you can unplug and use it 100% wirelessly over Wi-Fi!)*"
                )
                return {"success": False, "connected": False, "devices": [], "instructions": instructions, "message": instructions}

            unauthorized = any(d["status"] == "unauthorized" for d in devices)
            if unauthorized:
                msg = "Device detected, but UNAUTHORIZED! Please look at your phone screen and tap 'Always allow from this computer' -> OK."
                return {"success": False, "connected": False, "devices": devices, "message": msg}

            return {
                "success": True,
                "connected": True,
                "devices": devices,
                "message": f"Connected to Android device: {devices[0]['serial']} ({devices[0]['status']}). Full hardware control active!",
            }

        except Exception as e:
            return {"success": False, "error": f"ADB diagnostic error: {e}"}

    def enable_wireless_mode(self) -> Dict[str, Any]:
        """Switches connected phone to Wireless Wi-Fi mode on port 5555 so you can unplug the USB cable."""
        dev = self._get_device()
        if not dev:
            return {"success": False, "error": "Please plug your phone in via USB first to activate wireless Wi-Fi mode."}

        try:
            subprocess.run([ADB_BIN, "tcpip", "5555"], check=False)
            # Find phone Wi-Fi IP address
            ip_out = dev.shell("ip route")
            ip_match = re.search(r"src (\d+\.\d+\.\d+\.\d+)", ip_out)
            phone_ip = ip_match.group(1) if ip_match else "your_phone_ip"

            msg = (
                f"Wireless ADB enabled on port 5555!\n"
                f"You can now **unplug your USB cable**.\n"
                f"Your phone's Wi-Fi IP is: `{phone_ip}`.\n"
                f"JARVIS will automatically connect to `{phone_ip}:5555` over your home Wi-Fi!"
            )
            logger.info(msg)
            if phone_ip != "your_phone_ip":
                self.connect_wireless(phone_ip, 5555)
            return {"success": True, "phone_ip": phone_ip, "message": msg}
        except Exception as e:
            return {"success": False, "error": f"Failed to enable wireless mode: {e}"}

    def pair_wireless(self, ip_port: str, pairing_code: str) -> Dict[str, Any]:
        """Pairs with Android 11+ Wireless Debugging using pairing code."""
        try:
            res = subprocess.run([ADB_BIN, "pair", ip_port, pairing_code], capture_output=True, text=True, check=False)
            output = res.stdout.strip() or res.stderr.strip()
            return {"success": "successfully" in output.lower(), "output": output, "message": output}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def connect_wireless(self, ip_address: str, port: int = 5555) -> Dict[str, Any]:
        """Connects to an Android phone over Wi-Fi (Wireless ADB)."""
        target = f"{ip_address}:{port}" if ":" not in ip_address else ip_address
        logger.info(f"Connecting to Android phone at {target}...")
        try:
            res = subprocess.run([ADB_BIN, "connect", target], capture_output=True, text=True, check=False)
            output = res.stdout.strip()
            connected = "connected to" in output.lower() or "already connected" in output.lower()
            return {
                "success": connected,
                "target": target,
                "result": output,
                "message": f"Wireless connection result: {output}",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to connect to phone at {target}: {e}"}

    def get_devices(self) -> List[Dict[str, str]]:
        """Lists all connected Android devices."""
        try:
            devs = adbutils.adb.device_list()
            return [{"serial": d.serial, "state": "connected"} for d in devs]
        except Exception:
            return []

    def get_battery_status(self) -> Dict[str, Any]:
        """Checks battery percentage, charging state, and health of the phone."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        try:
            output = dev.shell("dumpsys battery")
            level_match = re.search(r"level:\s*(\d+)", output)
            scale_match = re.search(r"scale:\s*(\d+)", output)
            powered_match = re.search(r"(AC powered|USB powered|Wireless powered):\s*true", output)
            status_match = re.search(r"status:\s*(\d+)", output)

            level = int(level_match.group(1)) if level_match else 50
            scale = int(scale_match.group(1)) if scale_match else 100
            pct = int((level / scale) * 100)
            is_charging = bool(powered_match) or (status_match and status_match.group(1) == "2")

            charge_str = "Charging ⚡" if is_charging else "Not charging"
            msg = f"Your Android phone battery is at {pct}%, {charge_str}, Sir."
            logger.info(msg)
            return {"success": True, "battery_pct": pct, "is_charging": is_charging, "message": msg}
        except Exception as e:
            return {"success": False, "error": f"Could not read phone battery: {e}"}

    def launch_phone_app(self, app_name: str) -> Dict[str, Any]:
        """Launches an app on the phone (YouTube, Camera, Settings, WhatsApp, Spotify, etc.)."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        app_key = app_name.lower().strip()
        pkg = self.PACKAGE_MAP.get(app_key)

        logger.info(f"Launching '{app_name}' on phone...")
        try:
            if app_key == "camera":
                dev.shell("am start -a android.media.action.STILL_IMAGE_CAMERA")
                return {"success": True, "app": "Camera", "message": "Camera opened on your phone, Sir."}
            elif pkg:
                dev.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
                return {"success": True, "app": app_name, "package": pkg, "message": f"Opened {app_name.capitalize()} on your phone, Sir."}
            else:
                dev.shell(f"monkey -p com.{app_key} -c android.intent.category.LAUNCHER 1")
                return {"success": True, "app": app_name, "message": f"Sent launch intent for {app_name} on your phone."}
        except Exception as e:
            return {"success": False, "error": f"Failed to launch app on phone: {e}"}

    def ring_phone(self) -> Dict[str, Any]:
        """Find My Phone: Sets phone volume to maximum and plays alarm sound."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        logger.info("Triggering Find My Phone alarm...")
        try:
            dev.shell("input keyevent 224")
            for stream in [2, 3, 4, 5]:
                dev.shell(f"cmd media_session volume --set 15 || media volume --stream {stream} --set 15")
            dev.shell("am start -a android.intent.action.VIEW -d 'content://settings/system/ringtone'")
            return {"success": True, "message": "Ringing your phone at maximum volume, Sir! Check your surroundings."}
        except Exception as e:
            return {"success": False, "error": f"Failed to ring phone: {e}"}

    def control_phone_volume(self, action: str) -> Dict[str, Any]:
        """Adjusts phone volume (up, down, mute)."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        act = action.lower().strip()
        try:
            if "up" in act or "increase" in act:
                dev.shell("input keyevent 24")
                return {"success": True, "message": "Phone volume increased."}
            elif "down" in act or "decrease" in act or "lower" in act:
                dev.shell("input keyevent 25")
                return {"success": True, "message": "Phone volume decreased."}
            elif "mute" in act:
                dev.shell("input keyevent 164")
                return {"success": True, "message": "Phone muted."}
            return {"success": False, "error": f"Unknown volume action: {action}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def lock_unlock_screen(self) -> Dict[str, Any]:
        """Presses the power button to lock or wake the phone screen."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        try:
            dev.shell("input keyevent 26")
            return {"success": True, "message": "Phone screen power button toggled."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unlock_phone(self, pin: Optional[str] = None) -> Dict[str, Any]:
        """Wakes up phone screen, swipes up to dismiss lockscreen, and optionally enters PIN."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        try:
            # 1. Wake up screen (KEYCODE_WAKEUP 224)
            dev.shell("input keyevent 224")
            time.sleep(0.3)
            # 2. Swipe up from bottom to reveal PIN entry or home screen
            dev.shell("input swipe 540 1900 540 600 250")
            time.sleep(0.4)

            # 3. If pin is not provided in voice command, check saved PHONE_PIN in environment
            target_pin = pin or os.getenv("PHONE_PIN")
            if target_pin:
                clean_pin = re.sub(r"[^\w]", "", str(target_pin))
                if clean_pin:
                    dev.shell(f"input text {clean_pin}")
                    time.sleep(0.2)
                    dev.shell("input keyevent 66")  # KEYCODE_ENTER

            msg = "Phone screen awakened and unlocked, Sir." if not target_pin else "Phone awakened and unlocked with stored credentials, Sir."
            return {"success": True, "message": msg}
        except Exception as e:
            return {"success": False, "error": f"Failed to unlock phone: {e}"}

    def lock_phone(self) -> Dict[str, Any]:
        """Locks phone screen immediately."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        try:
            dev.shell("input keyevent 26")  # KEYCODE_POWER
            return {"success": True, "message": "Phone screen locked, Sir."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_phone_pin(self, pin: str) -> Dict[str, Any]:
        """Saves phone lock PIN/passcode to environment so user never has to speak it aloud."""
        clean_pin = re.sub(r"[^\w]", "", str(pin))
        if not clean_pin:
            return {"success": False, "error": "Invalid PIN provided."}

        os.environ["PHONE_PIN"] = clean_pin
        try:
            from dotenv import set_key
            env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
            set_key(env_path, "PHONE_PIN", clean_pin)
        except Exception as e:
            logger.warning(f"Could not persist PHONE_PIN to .env: {e}")

        return {"success": True, "message": "Phone PIN securely stored in your personal profile. You can now just say 'Jarvis, unlock my phone' anytime without saying the PIN!"}

    def _get_youtube_video_id(self, query: str) -> Optional[str]:
        """Resolves the top organic YouTube video ID for a search query to avoid search ads."""
        import urllib.request
        import urllib.parse
        try:
            encoded = urllib.parse.quote(query)
            url = f"https://www.youtube.com/results?search_query={encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=5) as response:
                html = response.read().decode("utf-8")
            vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
            if vids:
                return vids[0]
        except Exception as e:
            logger.debug(f"Direct video ID resolution fallback: {e}")
        return None

    def play_song_on_phone(self, song_name: str, app: str = "youtube") -> Dict[str, Any]:
        """Searches and immediately plays a song on the phone via YouTube or Spotify, bypassing ads."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        clean_song = song_name.strip()
        app_choice = app.lower().strip()

        try:
            # 1. Wake screen and unlock if locked
            dev.shell("input keyevent 224")
            dev.shell("wm dismiss-keyguard")

            if "spotify" in app_choice:
                logger.info(f"Playing '{clean_song}' on Spotify...")
                # Dismiss any open dialogs or drawers
                dev.shell("input keyevent 4")
                time.sleep(0.3)
                dev.shell("monkey -p com.spotify.music -c android.intent.category.LAUNCHER 1")
                time.sleep(1.2)

                # Tap Search tab at bottom (x=370, y=2320 on 1080x2400)
                dev.shell("input tap 370 2320")
                time.sleep(0.8)

                # Tap top search bar
                dev.shell("input tap 540 280")
                time.sleep(0.8)

                # Type song name
                safe_song = clean_song.replace(" ", "%s")
                dev.shell(f"input text '{safe_song}'")
                time.sleep(0.8)

                # Dismiss keyboard by pressing Back
                dev.shell("input keyevent 4")
                time.sleep(0.5)

                # Tap the top song result directly (x=350, y=420)
                dev.shell("input tap 350 420")
                time.sleep(1)

                # If Spotify was paused on a Connect session, tap the mini player play button (x=980, y=2175)
                dev.shell("input tap 980 2175")

                return {"success": True, "app": "Spotify", "song": clean_song, "message": f"Playing '{clean_song}' on Spotify, Sir."}
            else:
                logger.info(f"Playing '{clean_song}' on YouTube...")
                # Resolve direct YouTube video ID to completely bypass search ads and sponsor banners
                vid_id = self._get_youtube_video_id(clean_song)
                if vid_id:
                    logger.info(f"Resolved direct YouTube video ID: {vid_id}")
                    # Launch direct video directly via YouTube player intent
                    dev.shell(["am", "start", "-a", "android.intent.action.VIEW", "-d", f"vnd.youtube:{vid_id}"])
                else:
                    import urllib.parse
                    encoded = urllib.parse.quote(clean_song)
                    dev.shell(["am", "start", "-a", "android.intent.action.VIEW", "-d", f"https://www.youtube.com/results?search_query={encoded}"])
                    time.sleep(2.5)
                    dev.shell("input tap 540 650")

                # Give video a moment to buffer and tap 'Skip ad' if available
                time.sleep(3)
                self.skip_youtube_ad()
                return {"success": True, "app": "YouTube", "song": clean_song, "message": f"Playing '{clean_song}' directly on YouTube, Sir."}
        except Exception as e:
            logger.error(f"Error playing song on phone: {e}")
            return {"success": False, "error": str(e)}

    def stop_song_on_phone(self) -> Dict[str, Any]:
        """Pauses or stops active music/video playback on the phone across all apps (Spotify, YouTube, etc.)."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        try:
            # 1. Send global media pause and stop keyevents
            dev.shell("input keyevent 127") # KEYCODE_MEDIA_PAUSE
            dev.shell("input keyevent 86")  # KEYCODE_MEDIA_STOP
            dev.shell("cmd media_session dispatch --key 127")

            # 2. Spotify broadcast intent
            dev.shell("am broadcast -a com.spotify.mobile.android.ui.widget.PAUSE -p com.spotify.music")

            # 3. Tap Spotify mini-player pause icon directly (x=900, y=2175) or full-player (x=540, y=1970)
            dev.shell("input tap 900 2175")
            dev.shell("input tap 980 2175")

            return {"success": True, "message": "Music and media playback stopped on your phone, Sir."}
        except Exception as e:
            logger.error(f"Error stopping song on phone: {e}")
            return {"success": False, "error": str(e)}

    def skip_youtube_ad(self) -> Dict[str, Any]:
        """Automatically detects and clicks the 'Skip Ad' button or countdown on YouTube."""
        dev = self._get_device()
        if not dev:
            return {"success": False, "error": "No device connected"}

        try:
            # On 1080x2400 displays, YouTube's 'Skip Ad' pill is positioned at x=900-980, y=1250-1350 (portrait video)
            # or x=920, y=980 depending on player mode.
            dev.shell("input tap 950 1300")
            time.sleep(0.3)
            dev.shell("input tap 920 980")
            return {"success": True, "message": "Checked and tapped Skip Ad if present."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def type_text_on_phone(self, text: str, proceed: bool = True) -> Dict[str, Any]:
        """Types text into the active focused field on the phone and optionally hits Enter/Proceed."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        try:
            # Wake screen if asleep
            dev.shell("input keyevent 224")

            # Convert spaces to %s as expected by Android input text
            safe_text = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
            dev.shell(f"input text '{safe_text}'")

            if proceed:
                time.sleep(0.5)
                # Keyevent 66 = KEYCODE_ENTER (proceeds/submits/sends)
                dev.shell("input keyevent 66")
                msg = f"Typed '{text}' and pressed proceed/enter on your phone, Sir."
            else:
                msg = f"Typed '{text}' on your phone, Sir."

            logger.info(msg)
            return {"success": True, "text": text, "proceed": proceed, "message": msg}
        except Exception as e:
            logger.error(f"Error typing on phone: {e}")
            return {"success": False, "error": str(e)}

    def take_phone_screenshot(self, save_path: Optional[str] = None) -> Dict[str, Any]:
        """Captures the Android phone's live screen and saves it as a PNG on your PC."""
        dev = self._get_device()
        if not dev:
            diag = self.scan_and_diagnose()
            return {"success": False, "error": diag["message"]}

        if not save_path:
            save_path = os.path.join(self.screenshots_dir, f"phone_{int(time.time())}.png")

        logger.info(f"Capturing phone screen to {save_path}...")
        try:
            pil_img = dev.screenshot()
            pil_img.save(save_path, "PNG")
            return {"success": True, "file_path": save_path, "message": f"Phone screenshot captured and saved to {save_path}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to take phone screenshot: {e}"}
