import os
import glob
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger("files_tool")


class FilesTool:
    """Finds, inspects, and validates local files to share."""

    @staticmethod
    def get_user_directories() -> Dict[str, str]:
        user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        return {
            "downloads": os.path.join(user_profile, "Downloads"),
            "documents": os.path.join(user_profile, "Documents"),
            "desktop": os.path.join(user_profile, "Desktop"),
            "pictures": os.path.join(user_profile, "Pictures"),
            "screenshots": os.path.abspath("screenshots"),
        }

    def list_recent_files(self, folder_name: str = "downloads", limit: int = 5) -> List[Dict[str, Any]]:
        """Lists the most recently modified files in the specified folder."""
        dirs = self.get_user_directories()
        target_dir = dirs.get(folder_name.lower(), folder_name)

        if not os.path.exists(target_dir):
            return []

        files = []
        for entry in os.scandir(target_dir):
            if entry.is_file():
                files.append({
                    "name": entry.name,
                    "path": os.path.abspath(entry.path),
                    "size_kb": round(entry.stat().st_size / 1024, 1),
                    "modified_time": entry.stat().st_mtime,
                })

        # Sort by modification time descending
        files.sort(key=lambda x: x["modified_time"], reverse=True)
        return files[:limit]

    def find_file(self, query: str) -> Optional[str]:
        """Finds a file matching query name across common user directories or direct path."""
        # 1. Direct path check
        if os.path.exists(query):
            return os.path.abspath(query)

        dirs = self.get_user_directories()
        clean_query = query.lower().strip()

        # 2. Search across user folders
        for folder_path in dirs.values():
            if not os.path.exists(folder_path):
                continue
            for entry in os.scandir(folder_path):
                if entry.is_file() and clean_query in entry.name.lower():
                    return os.path.abspath(entry.path)

        return None
