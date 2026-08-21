"""
Smart file classifier for Unraid file organization.
Distinguishes between executable types, OS files, data files, etc.
"""

import os
import re
from pathlib import Path

try:
    import magic
    _HAS_MAGIC = True
except ImportError:
    magic = None
    _HAS_MAGIC = False
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Set
import logging

logger = logging.getLogger(__name__)


class FileCategory(Enum):
    """High-level file categories"""
    EXECUTABLE_WINDOWS = "executable_windows"
    EXECUTABLE_LINUX = "executable_linux"
    EXECUTABLE_MACOS = "executable_macos"
    EXECUTABLE_ANDROID = "executable_android"
    EXECUTABLE_UNKNOWN = "executable_unknown"
    OS_IMAGE = "os_image"
    OS_INSTALLER = "os_installer"
    GAME_ROM = "game_rom"
    HOMEBREW = "homebrew"
    ARCHIVE = "archive"
    DOCUMENT = "document"
    MEDIA_AUDIO = "media_audio"
    MEDIA_VIDEO = "media_video"
    MEDIA_IMAGE = "media_image"
    CODE_SOURCE = "code_source"
    CONFIG = "config"
    DATABASE = "database"
    LOG = "log"
    TEMP = "temp"
    UNKNOWN = "unknown"


class FileIntent(Enum):
    """What the file is likely used for"""
    MUSIC_PLAYER = "music_player"
    NETWORK_TOOL = "network_tool"
    SYSTEM_UTILITY = "system_utility"
    GAME = "game"
    DEVELOPMENT_TOOL = "development_tool"
    OFFICE_APP = "office_app"
    MEDIA_PLAYER = "media_player"
    ARCHIVE_TOOL = "archive_tool"
    OS_COMPONENT = "os_component"
    DRIVER = "driver"
    MALWARE_SUSPECT = "malware_suspect"
    EMULATOR = "emulator"
    HOMEBREW = "homebrew"
    DATA_FILE = "data_file"
    UNKNOWN = "unknown"


@dataclass
class FileClassification:
    """Result of file classification"""
    category: FileCategory
    intent: FileIntent
    confidence: float  # 0.0 to 1.0
    details: Dict[str, any]
    suggested_location: Optional[str] = None


class SmartFileClassifier:
    """
    Intelligently classifies files based on multiple signals:
    - File extension
    - Magic bytes / MIME type
    - Filename patterns
    - PE/ELF/Mach-O header analysis
    - String analysis for executables
    """

    # Windows executable patterns
    WINDOWS_EXE_PATTERNS = {
        'music_player': [
            r'.*(?:music|audio|player|winamp|foobar|aimp|musikcube|strawberry|clementine).*\.exe$',
            r'.*(?:spotify|itunes|musicbee|mediamonkey|dopamine).*\.exe$',
        ],
        'network_tool': [
            r'.*(?:putty|winscp|filezilla|wireshark|nmap|netcat|telnet|ssh|ftp|sftp).*\.exe$',
            r'.*(?:vpn|proxy|tunnel|openvpn|wireguard|tailscale|zerotier).*\.exe$',
            r'.*(?:browser|chrome|firefox|edge|opera|vivaldi).*\.exe$',
        ],
        'system_utility': [
            r'.*(?:ccleaner|defrag|disk|registry|cleaner|optimizer|tuneup|glary|advanced).*\.exe$',
            r'.*(?:taskmgr|procmon|procexp|autoruns|sysinternals).*\.exe$',
            r'.*(?:backup|restore|clone|image|acronis|macrium|veeam).*\.exe$',
        ],
        'game': [
            r'.*(?:steam|origin|epic|gog|ubisoft|battle\.net|riot).*\.exe$',
            r'.*(?:game|launcher|unreal|unity).*\.exe$',
        ],
        'development_tool': [
            r'.*(?:code|studio|intellij|pycharm|vscode|sublime|atom|notepad\+\+).*\.exe$',
            r'.*(?:git|docker|kubernetes|kubectl|terraform|ansible|vagrant).*\.exe$',
            r'.*(?:python|node|npm|yarn|pnpm|cargo|go|java|javac).*\.exe$',
        ],
        'emulator': [
            r'.*(?:epsxe|duckstation|pcsx2|ppsspp|rpcs3|ps3?emu).*\.exe$',
            r'.*(?:dolphin|project64|pj64|mupen64|simple64).*\.exe$',
            r'.*(?:snes9x|zsnes|bsnes|higan|mesen|fceux|nestopia|higan).*\.exe$',
            r'.*(?:retroarch|mame|cemu|yuzu|ryujinx|suyu|citra|melonds?|desmume).*\.exe$',
            r'.*(?:visualboyadvance|vba-?m|mgba|redream|demul|xenia|xemu|ares).*\.exe$',
        ],
        'malware_suspect': [
            r'.*(?:temp|tmp|cache|appdata|local|roaming).*\.exe$',
            r'^[a-f0-9]{8,}\.exe$',  # Random hex names
            r'.*(?:update|install|setup).*\.exe$',  # Generic installers in weird places
        ]
    }

    # Android APK patterns
    ANDROID_PATTERNS = {
        'music_player': [r'.*(?:music|audio|player|spotify|soundcloud|bandcamp).*\.apk$'],
        'network_tool': [r'.*(?:vpn|proxy|ssh|termux|connectbot|server|ftp).*\.apk$'],
        'system_utility': [r'.*(?:cleaner|booster|optimizer|battery|task|manager|file).*\.apk$'],
    }

    # OS image patterns
    OS_IMAGE_PATTERNS = [
        r'.*\.(?:iso|img|vhd|vhdx|vmdk|qcow2|raw|dmg)$',
        r'.*(?:ubuntu|debian|fedora|arch|mint|kali|centos|rhel|opensuse|manjaro|pop|elementary|zorin|garuda|endeavour).*\.(?:iso|img)$',
        r'.*(?:windows|win10|win11|server2016|server2019|server2022).*\.(?:iso|img|vhd|vhdx)$',
        r'.*(?:android|lineage|graphene|calyx|pixel|aosp).*\.(?:img|zip)$',
        r'.*(?:macos|osx|ventura|monterey|bigsur|catalina|mojave).*\.(?:dmg|iso)$',
    ]

    # Archive patterns
    ARCHIVE_EXTENSIONS = {
        '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.zst',
        '.tgz', '.tbz2', '.txz', '.tzst', '.lz4', '.lzma', '.cab'
    }

    # Console ROM extensions — unambiguous, map directly to a console slug
    CONSOLE_EXTS = {
        # Nintendo
        '.nes': 'nes', '.fds': 'nes', '.sfc': 'snes', '.smc': 'snes',
        '.z64': 'n64', '.n64': 'n64', '.v64': 'n64',
        '.gb': 'gb', '.gbc': 'gbc', '.gba': 'gba', '.vb': 'virtualboy',
        '.nds': 'nds', '.dsi': 'nds',
        '.3ds': '3ds', '.3dz': '3ds', '.cci': '3ds', '.cia': '3ds',
        '.nsp': 'switch', '.xci': 'switch',
        '.gcm': 'gamecube', '.rvz': 'wii', '.wbfs': 'wii', '.wia': 'wii', '.wad': 'wii',
        # Sega
        '.sms': 'sms', '.sg': 'sg1000', '.gen': 'genesis',
        '.cdi': 'dreamcast', '.gdi': 'dreamcast',
        # Sony
        '.cso': 'psp', '.pbp': 'psp',
        # Atari
        '.a26': 'atari2600', '.a78': 'atari7800', '.lnx': 'atarilynx',
        '.jag': 'jaguar', '.j64': 'jaguar', '.atr': 'atari8bit', '.msa': 'atarist',
        # Others
        '.pce': 'pcengine', '.col': 'colecovision', '.vec': 'vectrex',
        '.ws': 'wonderswan', '.wsc': 'wonderswan',
        '.ngp': 'neogeopocket', '.ngc': 'neogeopocket', '.neo': 'neogeo',
        '.xbe': 'xbox', '.xex': 'xbox360',
        '.gg': 'gamegear',
    }

    # Folder-name keywords -> console slug. Checked longest-first.
    CONSOLE_FOLDER_HINTS = {
        'super nintendo': 'snes', 'super famicom': 'snes', 'snes': 'snes',
        'nintendo 64': 'n64', 'n64': 'n64',
        'game boy advance': 'gba', 'gameboy advance': 'gba', 'gba': 'gba',
        'gameboy color': 'gbc', 'game boy color': 'gbc', 'gbc': 'gbc',
        'gameboy': 'gb', 'game boy': 'gb', 'gb': 'gb',
        'nintendo ds': 'nds', 'nds': 'nds', 'ds': 'nds',
        'nintendo 3ds': '3ds', '3ds': '3ds',
        'switch': 'switch',
        'famicom': 'nes', 'nes': 'nes',
        'virtual boy': 'virtualboy', 'virtualboy': 'virtualboy',
        'gamecube': 'gamecube', 'game cube': 'gamecube', 'gc': 'gamecube',
        'wii u': 'wiiu', 'wii': 'wii',
        'playstation': 'psx', 'psx': 'psx', 'ps1': 'psx',
        'ps2': 'ps2', 'ps3': 'ps3', 'psp': 'psp',
        'psvita': 'psvita', 'ps vita': 'psvita', 'vita': 'psvita',
        'dreamcast': 'dreamcast',
        'sega saturn': 'saturn', 'saturn': 'saturn',
        'sega genesis': 'genesis', 'genesis': 'genesis',
        'megadrive': 'genesis', 'mega drive': 'genesis', 'megadrive': 'genesis',
        'master system': 'sms', 'sega master': 'sms', 'sms': 'sms',
        'sega cd': 'segacd', 'segacd': 'segacd', 'mega cd': 'segacd', 'megacd': 'segacd',
        'sega 32x': 'sega32x', '32x': 'sega32x',
        'gamegear': 'gamegear', 'game gear': 'gamegear', 'gg': 'gamegear',
        'sg1000': 'sg1000', 'sg-1000': 'sg1000',
        'pc engine': 'pcengine', 'pcengine': 'pcengine',
        'turbografx': 'pcengine', 'turbo grafx': 'pcengine', 'pce': 'pcengine',
        'atari 2600': 'atari2600', 'atari2600': 'atari2600', '2600': 'atari2600',
        'atari 7800': 'atari7800', 'atari7800': 'atari7800', '7800': 'atari7800',
        'atari lynx': 'atarilynx', 'atarilynx': 'atarilynx', 'lynx': 'atarilynx',
        'atari 8bit': 'atari8bit', 'atari8bit': 'atari8bit',
        'jaguar': 'jaguar',
        'colecovision': 'colecovision', 'coleco': 'colecovision',
        'vectrex': 'vectrex',
        'wonderswan': 'wonderswan', 'wonder swan': 'wonderswan',
        'neo geo pocket': 'neogeopocket', 'neogeo pocket': 'neogeopocket',
        'neo geo': 'neogeo', 'neogeo': 'neogeo',
        'xbox 360': 'xbox360', 'xbox360': 'xbox360', 'xbox': 'xbox',
    }
    CONSOLE_FOLDER_HINT_KEYS = sorted(CONSOLE_FOLDER_HINTS, key=len, reverse=True)

    # Homebrew-specific executables (per-console homebrew apps)
    HOMEBREW_EXTS = {
        '.3dsx': '3ds', '.dol': 'wii', '.vpk': 'psvita', '.elf': None,  # .elf handled elsewhere
    }

    # Disc images that could be OS installers OR console game discs
    DISC_AMBIGUOUS_EXTS = {'.iso', '.bin', '.cue', '.img', '.chd', '.mdf', '.mds', '.ecm'}

    REGION_TAG_RE = re.compile(
        r"\((?:USA|US|EUR|EUROPE|EU|JAP|JAPAN|JP|WORLD|AUS|NL|IT|SP|FR|DE|SC|SE|NO|DK|FI|PT|BR|CAN|MEX|ASIA|KOR|CHN|HKG)\)",
        re.IGNORECASE,
    )
    CONSOLE_WORD_HINTS = {
        'psx': 'psx', 'playstation 1': 'psx', 'playstation1': 'psx',
        'ps2': 'ps2', 'playstation 2': 'ps2', 'playstation2': 'ps2',
        'ps3': 'ps3', 'psp': 'psp', 'ps vita': 'psvita', 'psvita': 'psvita',
        'gamecube': 'gamecube', 'game cube': 'gamecube',
        'wii u': 'wiiu', 'wii': 'wii', 'switch': 'switch',
        'dreamcast': 'dreamcast', 'saturn': 'saturn',
        'sega cd': 'segacd', 'segacd': 'segacd', 'mega cd': 'segacd', 'megacd': 'segacd',
        '32x': 'sega32x', '3do': '3do', 'jaguar': 'jaguar',
        'xbox': 'xbox', 'pc engine': 'pcengine', 'pcengine': 'pcengine',
        'turbografx': 'pcengine', 'neo geo': 'neogeo', 'neogeo': 'neogeo',
    }

    # Media extensions
    AUDIO_EXTENSIONS = {'.mp3', '.flac', '.wav', '.ogg', '.m4a', '.aac', '.opus', '.wma', '.ape', '.alac', '.dts', '.ac3'}
    VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg', '.ts', '.m2ts', '.vob', '.ogv'}
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic', '.heif', '.avif', '.svg', '.raw', '.cr2', '.nef', '.arw', '.dng'}

    # Document extensions
    DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp', '.txt', '.rtf', '.md', '.tex'}

    # Code extensions
    CODE_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h', '.hpp', '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala', '.clj', '.hs', '.ml', '.fs', '.vb', '.pl', '.sh', '.bat', '.ps1', '.sql', '.html', '.css', '.scss', '.less', '.vue', '.svelte', '.json', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf'}

    def __init__(self):
        self.magic = magic.Magic(mime=True) if _HAS_MAGIC else None
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance"""
        self.compiled_windows = {}
        for intent, patterns in self.WINDOWS_EXE_PATTERNS.items():
            self.compiled_windows[FileIntent(intent)] = [re.compile(p, re.IGNORECASE) for p in patterns]

        self.compiled_android = {}
        for intent, patterns in self.ANDROID_PATTERNS.items():
            self.compiled_android[FileIntent(intent)] = [re.compile(p, re.IGNORECASE) for p in patterns]

        self.compiled_os_images = [re.compile(p, re.IGNORECASE) for p in self.OS_IMAGE_PATTERNS]

    def classify(self, file_path: Path) -> FileClassification:
        """
        Classify a single file using multiple detection methods.
        Returns a FileClassification with category, intent, and confidence.
        """
        if not file_path.exists():
            return FileClassification(
                category=FileCategory.UNKNOWN,
                intent=FileIntent.UNKNOWN,
                confidence=0.0,
                details={'error': 'File does not exist'}
            )

        # Get basic info
        stat = file_path.stat()
        filename = file_path.name.lower()
        extension = file_path.suffix.lower()

        details = {
            'filename': file_path.name,
            'extension': extension,
            'size': stat.st_size,
            'size_human': self._human_size(stat.st_size),
        }

        # 0. Console ROMs / homebrew — most specific extensions win first
        rom = self._detect_console_rom(extension, filename, file_path)
        if rom is not None:
            cat, console_slug, conf = rom
            intent = FileIntent.GAME if cat == FileCategory.GAME_ROM else FileIntent.HOMEBREW
            details['console'] = console_slug
            return FileClassification(
                category=cat,
                intent=intent,
                confidence=conf,
                details=details,
                suggested_location=self._suggest_location(cat, intent, console=console_slug),
            )

        # 1. Check by extension first (fastest)
        category = self._classify_by_extension(extension, filename)
        if category != FileCategory.UNKNOWN:
            intent = self._determine_intent(filename, category, file_path)
            return FileClassification(
                category=category,
                intent=intent,
                confidence=0.8,
                details=details,
                suggested_location=self._suggest_location(category, intent)
            )

        # 2. Check by magic bytes / MIME type
        if self.magic is not None:
            try:
                mime_type = self.magic.from_file(str(file_path))
                details['mime_type'] = mime_type
                category = self._classify_by_mime(mime_type, filename)
                if category != FileCategory.UNKNOWN:
                    intent = self._determine_intent(filename, category, file_path)
                    return FileClassification(
                        category=category,
                        intent=intent,
                        confidence=0.85,
                        details=details,
                        suggested_location=self._suggest_location(category, intent)
                    )
            except Exception as e:
                logger.debug(f"Magic detection failed for {file_path}: {e}")

        # 3. Deep analysis for executables and disk images
        if extension in {'.exe', '.dll', '.sys', '.apk', '.app', '.deb', '.rpm', '.msi',
                         '.iso', '.img', '.vhd', '.vhdx', '.vmdk', '.qcow2', '.dmg'}:
            return self._deep_executable_analysis(file_path, filename, details)

        # 4. Filename pattern matching
        category = self._classify_by_filename_patterns(filename)
        if category != FileCategory.UNKNOWN:
            intent = self._determine_intent(filename, category, file_path)
            return FileClassification(
                category=category,
                intent=intent,
                confidence=0.7,
                details=details,
                suggested_location=self._suggest_location(category, intent)
            )

        return FileClassification(
            category=FileCategory.UNKNOWN,
            intent=FileIntent.UNKNOWN,
            confidence=0.1,
            details=details,
            suggested_location=None
        )

    def _detect_console_rom(self, extension: str, filename: str, file_path: Path = None):
        """Return (category, console_slug, confidence) for ROM/homebrew files, else None.

        Unambiguous cart/disc extensions map directly. Zipped ROMs are identified
        by peeking at the contained file extensions. Ambiguous disc images
        (.iso/.bin/…) only become ROMs when a region tag, verified-dump marker,
        or explicit console word is present — otherwise OS-image handling applies.
        """
        if extension in self.CONSOLE_EXTS:
            return (FileCategory.GAME_ROM, self.CONSOLE_EXTS[extension], 0.95)
        if extension in self.HOMEBREW_EXTS and self.HOMEBREW_EXTS[extension]:
            return (FileCategory.HOMEBREW, self.HOMEBREW_EXTS[extension], 0.9)

        if extension == '.zip' and file_path is not None:
            zipped = self._console_from_zip(file_path)
            if zipped:
                cat, console_slug = zipped
                conf = 0.9 if cat == FileCategory.GAME_ROM else 0.85
                return (cat, console_slug, conf)
            # Contents unknown — the folder it lives in is the next-best hint
            hint = self._console_from_folder(file_path.parent)
            if hint:
                return (FileCategory.GAME_ROM, hint, 0.75)
            return None  # not a ROM zip — fall through to archive handling

        # Extension-less files inside console-named folders (some flash-cart dumps)
        if extension == '' and file_path is not None:
            hint = self._console_from_folder(file_path.parent)
            if hint:
                return (FileCategory.GAME_ROM, hint, 0.7)

        if extension in self.DISC_AMBIGUOUS_EXTS:
            # Known OS installers keep their existing routing
            if any(p.match(filename) for p in self.compiled_os_images):
                return None
            hint = self._console_word(filename)
            if hint:
                return (FileCategory.GAME_ROM, hint, 0.85)
            if self.REGION_TAG_RE.search(filename) or '[!]' in filename:
                return (FileCategory.GAME_ROM, 'disc', 0.8)
        return None

    def _console_from_zip(self, file_path: Path):
        """Identify a zipped ROM by its contained file extensions.

        Reads only the zip's central directory (no decompression). Returns
        (category, console_slug) when a console majority is found, else None.
        """
        import zipfile
        from collections import Counter
        try:
            with zipfile.ZipFile(file_path) as z:
                names = [n for n in z.namelist() if not n.endswith('/')][:200]
        except Exception:
            return None

        exts = []
        for name in names:
            dot = name.rfind('.')
            if dot >= 0:
                exts.append(name[dot:].lower())

        console_votes = Counter(
            self.CONSOLE_EXTS[e] for e in exts if e in self.CONSOLE_EXTS
        )
        if console_votes:
            return (FileCategory.GAME_ROM, console_votes.most_common(1)[0][0])

        homebrew_votes = Counter(
            self.HOMEBREW_EXTS[e] for e in exts
            if e in self.HOMEBREW_EXTS and self.HOMEBREW_EXTS[e]
        )
        if homebrew_votes:
            return (FileCategory.HOMEBREW, homebrew_votes.most_common(1)[0][0])

        return None

    def _console_from_folder(self, dir_path: Path, max_levels: int = 2) -> Optional[str]:
        """Walk up a couple of folder levels looking for a console-named directory."""
        d = dir_path
        for _ in range(max_levels):
            name = d.name.lower()
            if name:
                for kw in self.CONSOLE_FOLDER_HINT_KEYS:
                    if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", name):
                        return self.CONSOLE_FOLDER_HINTS[kw]
            d = d.parent
        return None

    def _console_word(self, filename: str) -> Optional[str]:
        lowered = filename.lower()
        for word, slug in self.CONSOLE_WORD_HINTS.items():
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                return slug
        return None

    def _classify_by_extension(self, extension: str, filename: str) -> FileCategory:
        """Quick classification by file extension"""
        if extension in {'.exe', '.dll', '.sys', '.bat', '.cmd', '.com', '.scr', '.msi', '.ps1'}:
            return FileCategory.EXECUTABLE_WINDOWS
        elif extension in {'.apk', '.aab', '.xapk'}:
            return FileCategory.EXECUTABLE_ANDROID
        elif extension in {'.app', '.dmg', '.pkg', '.mpkg'}:
            return FileCategory.EXECUTABLE_MACOS
        elif extension in {'.elf', '.so', '.bin', '.out', '.run', '.AppImage', '.snap', '.flatpak'}:
            return FileCategory.EXECUTABLE_LINUX
        elif extension in self.ARCHIVE_EXTENSIONS:
            return FileCategory.ARCHIVE
        elif extension in self.AUDIO_EXTENSIONS:
            return FileCategory.MEDIA_AUDIO
        elif extension in self.VIDEO_EXTENSIONS:
            return FileCategory.MEDIA_VIDEO
        elif extension in self.IMAGE_EXTENSIONS:
            return FileCategory.MEDIA_IMAGE
        elif extension in self.DOCUMENT_EXTENSIONS:
            return FileCategory.DOCUMENT
        elif extension in self.CODE_EXTENSIONS:
            return FileCategory.CODE_SOURCE
        elif extension in {'.log', '.log.', '.log.'}:
            return FileCategory.LOG
        elif extension in {'.tmp', '.temp', '.cache', '.swp', '.bak', '~'}:
            return FileCategory.TEMP
        elif extension in {'.conf', '.config', '.cfg', '.ini', '.yaml', '.yml', '.toml', '.env'}:
            return FileCategory.CONFIG
        elif extension in {'.db', '.sqlite', '.sqlite3', '.mdb', '.accdb', '.realm'}:
            return FileCategory.DATABASE
        return FileCategory.UNKNOWN

    def _classify_by_mime(self, mime_type: str, filename: str) -> FileCategory:
        """Classify by MIME type"""
        mime_lower = mime_type.lower()

        if 'executable' in mime_lower or 'x-executable' in mime_lower:
            if 'windows' in mime_lower or 'msdos' in mime_lower:
                return FileCategory.EXECUTABLE_WINDOWS
            elif 'android' in mime_lower:
                return FileCategory.EXECUTABLE_ANDROID
            elif 'mach-o' in mime_lower or 'apple' in mime_lower:
                return FileCategory.EXECUTABLE_MACOS
            else:
                return FileCategory.EXECUTABLE_LINUX
        elif 'archive' in mime_lower or 'compressed' in mime_lower or 'zip' in mime_lower:
            return FileCategory.ARCHIVE
        elif 'audio' in mime_lower:
            return FileCategory.MEDIA_AUDIO
        elif 'video' in mime_lower:
            return FileCategory.MEDIA_VIDEO
        elif 'image' in mime_lower:
            return FileCategory.MEDIA_IMAGE
        elif 'text' in mime_lower or 'document' in mime_lower or 'pdf' in mime_lower:
            return FileCategory.DOCUMENT
        elif 'database' in mime_lower or 'sqlite' in mime_lower:
            return FileCategory.DATABASE
        return FileCategory.UNKNOWN

    def _classify_by_filename_patterns(self, filename: str) -> FileCategory:
        """Classify by filename patterns (OS images, etc.)"""
        for pattern in self.compiled_os_images:
            if pattern.match(filename):
                return FileCategory.OS_IMAGE
        return FileCategory.UNKNOWN

    def _deep_executable_analysis(self, file_path: Path, filename: str, details: Dict) -> FileClassification:
        """Deep analysis of executable files"""
        extension = file_path.suffix.lower()

        if extension == '.exe' or extension == '.dll':
            return self._analyze_windows_executable(file_path, filename, details)
        elif extension == '.apk':
            return self._analyze_android_apk(file_path, filename, details)
        elif extension in {'.iso', '.img', '.vhd', '.vhdx', '.vmdk', '.qcow2', '.dmg'}:
            return self._analyze_os_image(file_path, filename, details)

        return FileClassification(
            category=FileCategory.EXECUTABLE_UNKNOWN,
            intent=FileIntent.UNKNOWN,
            confidence=0.5,
            details=details
        )

    def _analyze_windows_executable(self, file_path: Path, filename: str, details: Dict) -> FileClassification:
        """Analyze Windows PE executable for intent"""
        try:
            # Read PE header
            with open(file_path, 'rb') as f:
                header = f.read(4096)

            details['pe_header'] = True

            # Check for PE signature
            if header[0:2] == b'MZ':
                pe_offset = int.from_bytes(header[0x3C:0x40], 'little')
                if pe_offset < len(header) and header[pe_offset:pe_offset+4] == b'PE\x00\x00':
                    details['is_pe'] = True

                    # Extract strings for intent analysis
                    strings = self._extract_strings(header)
                    details['strings_sample'] = strings[:50]

                    # Determine intent from strings and filename
                    intent = self._determine_windows_intent(filename, strings)
                    confidence = 0.9 if intent != FileIntent.UNKNOWN else 0.6

                    return FileClassification(
                        category=FileCategory.EXECUTABLE_WINDOWS,
                        intent=intent,
                        confidence=confidence,
                        details=details,
                        suggested_location=self._suggest_location(FileCategory.EXECUTABLE_WINDOWS, intent)
                    )
        except Exception as e:
            logger.debug(f"PE analysis failed for {file_path}: {e}")

        # Fallback to filename-based
        intent = self._determine_windows_intent(filename, [])
        return FileClassification(
            category=FileCategory.EXECUTABLE_WINDOWS,
            intent=intent,
            confidence=0.6,
            details=details,
            suggested_location=self._suggest_location(FileCategory.EXECUTABLE_WINDOWS, intent)
        )

    def _analyze_android_apk(self, file_path: Path, filename: str, details: Dict) -> FileClassification:
        """Analyze Android APK"""
        try:
            import zipfile
            with zipfile.ZipFile(file_path, 'r') as z:
                # Check for AndroidManifest.xml
                if 'AndroidManifest.xml' in z.namelist():
                    details['has_manifest'] = True
                    manifest = z.read('AndroidManifest.xml')
                    details['manifest_size'] = len(manifest)

                    # Extract package name and permissions from manifest (simplified)
                    manifest_str = manifest.decode('utf-8', errors='ignore')
                    if 'android.permission.INTERNET' in manifest_str:
                        details['has_internet'] = True

            intent = self._determine_android_intent(filename)
            return FileClassification(
                category=FileCategory.EXECUTABLE_ANDROID,
                intent=intent,
                confidence=0.85,
                details=details,
                suggested_location=self._suggest_location(FileCategory.EXECUTABLE_ANDROID, intent)
            )
        except Exception as e:
            logger.debug(f"APK analysis failed for {file_path}: {e}")

        return FileClassification(
            category=FileCategory.EXECUTABLE_ANDROID,
            intent=FileIntent.UNKNOWN,
            confidence=0.5,
            details=details
        )

    def _analyze_os_image(self, file_path: Path, filename: str, details: Dict) -> FileClassification:
        """Analyze OS image files"""
        # Determine OS type from filename
        os_type = 'unknown'
        filename_lower = filename.lower()

        if any(x in filename_lower for x in ['ubuntu', 'debian', 'mint', 'kali', 'pop', 'elementary', 'zorin']):
            os_type = 'linux_debian'
        elif any(x in filename_lower for x in ['fedora', 'centos', 'rhel', 'rocky', 'alma']):
            os_type = 'linux_redhat'
        elif any(x in filename_lower for x in ['arch', 'manjaro', 'endeavour', 'garuda']):
            os_type = 'linux_arch'
        elif any(x in filename_lower for x in ['opensuse', 'suse']):
            os_type = 'linux_suse'
        elif any(x in filename_lower for x in ['windows', 'win10', 'win11', 'server2016', 'server2019', 'server2022']):
            os_type = 'windows'
        elif any(x in filename_lower for x in ['android', 'lineage', 'graphene', 'calyx', 'pixel', 'aosp']):
            os_type = 'android'
        elif any(x in filename_lower for x in ['macos', 'osx', 'ventura', 'monterey', 'bigsur', 'catalina', 'mojave']):
            os_type = 'macos'

        details['os_type'] = os_type

        return FileClassification(
            category=FileCategory.OS_IMAGE,
            intent=FileIntent.OS_COMPONENT,
            confidence=0.95,
            details=details,
            suggested_location=f"/mnt/user/data/isos/{os_type}/"
        )

    def _extract_strings(self, data: bytes, min_len: int = 4) -> List[str]:
        """Extract ASCII strings from binary data"""
        strings = []
        current = []
        for byte in data:
            if 32 <= byte <= 126:  # Printable ASCII
                current.append(chr(byte))
            else:
                if len(current) >= min_len:
                    strings.append(''.join(current))
                current = []
        if len(current) >= min_len:
            strings.append(''.join(current))
        return strings

    def _determine_windows_intent(self, filename: str, strings: List[str]) -> FileIntent:
        """Determine intent of Windows executable"""
        filename_lower = filename.lower()
        all_text = ' '.join(strings).lower() + ' ' + filename_lower

        # Check each intent category
        for intent, patterns in self.compiled_windows.items():
            for pattern in patterns:
                if pattern.search(filename_lower):
                    return intent

        # Check strings for additional clues
        if any(x in all_text for x in ['bass', 'ffmpeg', 'libvlc', 'mediafoundation', 'directsound', 'wasapi', 'asio']):
            return FileIntent.MUSIC_PLAYER
        if any(x in all_text for x in ['winsock', 'winhttp', 'wininet', 'openssl', 'curl', 'websocket', 'tcp', 'udp', 'dns', 'dhcp']):
            return FileIntent.NETWORK_TOOL
        if any(x in all_text for x in ['directx', 'opengl', 'vulkan', 'dxgi', 'd3d', 'gdi', 'user32', 'kernel32']):
            return FileIntent.GAME
        if any(x in all_text for x in ['msvcrt', 'vcruntime', 'ucrtbase', 'api-ms-win']):
            return FileIntent.SYSTEM_UTILITY

        return FileIntent.UNKNOWN

    def _determine_android_intent(self, filename: str) -> FileIntent:
        """Determine intent of Android APK"""
        filename_lower = filename.lower()
        for intent, patterns in self.compiled_android.items():
            for pattern in patterns:
                if pattern.search(filename_lower):
                    return intent
        return FileIntent.UNKNOWN

    def _determine_intent(self, filename: str, category: FileCategory, file_path: Path) -> FileIntent:
        """Determine file intent based on category and filename"""
        if category == FileCategory.EXECUTABLE_WINDOWS:
            return self._determine_windows_intent(filename, [])
        elif category == FileCategory.EXECUTABLE_ANDROID:
            return self._determine_android_intent(filename)
        elif category == FileCategory.OS_IMAGE:
            return FileIntent.OS_COMPONENT
        elif category == FileCategory.ARCHIVE:
            return FileIntent.ARCHIVE_TOOL
        return FileIntent.DATA_FILE

    def _suggest_location(self, category: FileCategory, intent: FileIntent, console: Optional[str] = None) -> Optional[str]:
        """Suggest a location following TRaSH-Guides-style /data root layout."""
        base = "/mnt/user/data"

        if category == FileCategory.GAME_ROM:
            return f"{base}/roms/{console or 'unknown'}/"
        if category == FileCategory.HOMEBREW:
            return f"{base}/homebrew/{console or 'unknown'}/"

        suggestions = {
            FileCategory.EXECUTABLE_WINDOWS: {
                FileIntent.MUSIC_PLAYER: f"{base}/apps/windows/media/",
                FileIntent.MEDIA_PLAYER: f"{base}/apps/windows/media/",
                FileIntent.NETWORK_TOOL: f"{base}/apps/windows/network/",
                FileIntent.SYSTEM_UTILITY: f"{base}/apps/windows/utilities/",
                FileIntent.ARCHIVE_TOOL: f"{base}/apps/windows/utilities/",
                FileIntent.OFFICE_APP: f"{base}/apps/windows/office/",
                FileIntent.DEVELOPMENT_TOOL: f"{base}/apps/windows/development/",
                FileIntent.EMULATOR: f"{base}/emulators/windows/",
                FileIntent.DRIVER: f"{base}/apps/windows/drivers/",
                FileIntent.GAME: f"{base}/games/windows/",
                FileIntent.MALWARE_SUSPECT: f"{base}/quarantine/",
            },
            FileCategory.EXECUTABLE_ANDROID: {
                FileIntent.MUSIC_PLAYER: f"{base}/apps/android/media/",
                FileIntent.MEDIA_PLAYER: f"{base}/apps/android/media/",
                FileIntent.NETWORK_TOOL: f"{base}/apps/android/network/",
                FileIntent.SYSTEM_UTILITY: f"{base}/apps/android/utilities/",
                FileIntent.EMULATOR: f"{base}/emulators/android/",
                FileIntent.GAME: f"{base}/games/android/",
            },
            FileCategory.EXECUTABLE_LINUX: {
                FileIntent.DATA_FILE: f"{base}/apps/linux/",
                FileIntent.EMULATOR: f"{base}/emulators/linux/",
                FileIntent.UNKNOWN: f"{base}/apps/linux/",
            },
            FileCategory.EXECUTABLE_MACOS: {
                FileIntent.DATA_FILE: f"{base}/apps/macos/",
                FileIntent.UNKNOWN: f"{base}/apps/macos/",
            },
            FileCategory.OS_IMAGE: {
                FileIntent.OS_COMPONENT: f"{base}/isos/",
            },
            FileCategory.MEDIA_AUDIO: {
                FileIntent.DATA_FILE: f"{base}/media/music/",
            },
            FileCategory.MEDIA_VIDEO: {
                FileIntent.DATA_FILE: f"{base}/media/movies/",
            },
            FileCategory.MEDIA_IMAGE: {
                FileIntent.DATA_FILE: f"{base}/media/photos/",
            },
            FileCategory.DOCUMENT: {
                FileIntent.DATA_FILE: f"{base}/documents/",
            },
            FileCategory.ARCHIVE: {
                FileIntent.ARCHIVE_TOOL: f"{base}/archives/",
                FileIntent.DATA_FILE: f"{base}/archives/",
            },
            FileCategory.CODE_SOURCE: {
                FileIntent.DATA_FILE: f"{base}/code/",
            },
        }

        cat_suggestions = suggestions.get(category, {})
        return cat_suggestions.get(intent, cat_suggestions.get(FileIntent.DATA_FILE))

    def _human_size(self, size: int) -> str:
        """Convert bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"


    def classify_folder(self, dir_path: Path, info: Optional[dict] = None) -> FileClassification:
        """Classify a whole app/game folder as one movable unit."""
        if info is None:
            info = detect_folder_unit(dir_path) or {}
        primary_name = info.get("primary_exe")
        intent = (
            self._determine_windows_intent(primary_name.lower(), [])
            if primary_name else FileIntent.SYSTEM_UTILITY
        )
        return FileClassification(
            category=FileCategory.EXECUTABLE_WINDOWS,
            intent=intent,
            confidence=0.9,
            details={
                "folder_unit": True,
                "file_count": info.get("file_count", 0),
                "size": info.get("size", 0),
                "primary_exe": primary_name,
            },
            suggested_location=self._suggest_location(FileCategory.EXECUTABLE_WINDOWS, intent),
        )


# Known platform/launcher artifacts — their presence marks a folder as a game/app unit
LAUNCHER_MARKER_FILES = {
    "steam_api.dll", "steam_api64.dll", "steam_appid.txt", "steam_emu.ini",
    "smartsteamemu.dll", "smartsteamemu64.dll", "ali213.ini", "codex.ini",
    "cream_api.ini", "online_fix.ini", "unityplayer.dll", "unitycrashhandler32.exe",
    "unitycrashhandler64.exe", "anadius.cfg", "gog.ico", "unins000.exe",
    "heroic.exe", "legendary.ini",
}

# Engine data archives that (with an exe) indicate a game unit
ENGINE_DATA_EXTS = {".pck", ".pak", ".bsa", ".ba2", ".vpk", ".wad", ".gcf", ".arc", ".big"}

# Caps so detection stays cheap on huge trees
_UNIT_MAX_SUBDIRS = 20
_UNIT_MAX_ENTRIES = 800


def detect_folder_unit(dir_path: Path) -> Optional[dict]:
    """Phase-2 unit detection.

    A directory is a portable app/game unit when any of these hold across its
    own files plus one level of subdirectories:
      - classic cluster: 1+ exe and 3+ dll among 5+ files
      - launcher artifact: a known marker file alongside an exe
      - engine data: an exe next to engine archive(s) (.pck/.pak/.bsa/…)

    Returns {primary_exe, file_count, size} or None.
    """
    try:
        top = sorted(dir_path.iterdir(), key=lambda p: p.name)
    except OSError:
        return None

    files_top = [p for p in top if p.is_file()]
    subdirs = [p for p in top if p.is_dir()]

    nested = []
    budget = _UNIT_MAX_ENTRIES - len(files_top)
    for sd in subdirs[:_UNIT_MAX_SUBDIRS]:
        if budget <= 0:
            break
        try:
            for f in sd.iterdir():
                if f.is_file():
                    nested.append(f)
                    budget -= 1
                    if budget <= 0:
                        break
        except OSError:
            continue

    all_files = files_top + nested
    all_names = [f.name.lower() for f in all_files]
    n_exe = sum(1 for n in all_names if n.endswith(".exe"))
    n_dll = sum(1 for n in all_names if n.endswith(".dll"))
    total = len(all_names)

    markers = LAUNCHER_MARKER_FILES.intersection(all_names)
    has_engine_data = any(n.endswith(tuple(ENGINE_DATA_EXTS)) for n in all_names)

    is_unit = (
        (n_exe >= 1 and n_dll >= 3 and total >= 5)
        or (n_exe >= 1 and bool(markers))
        or (n_exe >= 1 and has_engine_data)
    )
    if not is_unit:
        return None

    exes = [f for f in all_files if f.name.lower().endswith(".exe")]
    primary = max(exes, key=lambda p: p.stat().st_size) if exes else None
    size = sum(f.stat().st_size for f in all_files)
    return {
        "primary_exe": primary.name if primary else None,
        "file_count": total,
        "size": size,
    }


def looks_like_app_folder(filenames: List[str]) -> bool:
    """Heuristic: a directory is a portable app/game unit when it holds an
    executable plus several DLLs/data files — move it whole, not file-by-file."""
    lower = [f.lower() for f in filenames]
    n_exe = sum(1 for f in lower if f.endswith(".exe"))
    n_dll = sum(1 for f in lower if f.endswith(".dll"))
    return n_exe >= 1 and n_dll >= 3 and len(lower) >= 5


def scan_directory(root: Path, classifier: SmartFileClassifier, max_files: int = 10000) -> List[FileClassification]:
    """Scan a directory and classify all files"""
    results = []
    count = 0

    for file_path in root.rglob('*'):
        if file_path.is_file():
            classification = classifier.classify(file_path)
            classification.details['full_path'] = str(file_path)
            classification.details['relative_path'] = str(file_path.relative_to(root))
            results.append(classification)
            count += 1
            if count >= max_files:
                logger.warning(f"Reached max files limit ({max_files})")
                break

    return results