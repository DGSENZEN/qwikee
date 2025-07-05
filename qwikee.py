#!/usr/bin/env python3
"""
🚀 Qwikee - Quick Minecraft Mod Installer
A comprehensive tool for downloading and installing Minecraft mods from CurseForge and direct URLs.
"""

import os
import sys
import json
import re
import time
import hashlib
import shutil
import platform
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Optional, Tuple
import zipfile
import tempfile
import logging
from dataclasses import dataclass, asdict
from datetime import datetime

import requests
import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.text import Text
from rich.logging import RichHandler
from rich.status import Status
from rich.markdown import Markdown

# Initialize console and logging
console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, show_path=False)]
)
logger = logging.getLogger("qwikee")

# Constants
DEFAULT_MINECRAFT_PATHS = {
    "Windows": [
        os.path.expanduser("~\\AppData\\Roaming\\.minecraft"),
        os.path.expanduser("~\\Documents\\Twitch\\Minecraft\\Install"),
        os.path.expanduser("~\\Documents\\Curse\\Minecraft\\Install"),
        os.path.expanduser("~\\Documents\\GDLauncher\\instances"),
    ],
    "Darwin": [  # macOS
        os.path.expanduser("~/Library/Application Support/minecraft"),
        os.path.expanduser("~/Documents/Twitch/Minecraft/Install"),
        os.path.expanduser("~/Documents/Curse/Minecraft/Install"),
    ],
    "Linux": [
        os.path.expanduser("~/.minecraft"),
        os.path.expanduser("~/snap/minecraft-launcher/common/.minecraft"),
        os.path.expanduser("~/.local/share/multimc/instances"),
        os.path.expanduser("~/.local/share/PrismLauncher/instances"),
    ]
}

@dataclass
class ModInfo:
    """Data class for mod information"""
    name: str
    filename: str
    download_url: str
    file_size: Optional[int] = None
    mod_id: Optional[int] = None
    file_id: Optional[int] = None
    version: Optional[str] = None
    minecraft_versions: Optional[List[str]] = None
    description: Optional[str] = None
    sha1_hash: Optional[str] = None

class QwikeeConfig:
    """Manages Qwikee configuration and settings"""
    
    def __init__(self):
        self.config_dir = Path.home() / ".qwikee"
        self.config_file = self.config_dir / "config.json"
        self.config = self.load_config()
    
    def load_config(self) -> Dict:
        """Load configuration from file"""
        default_config = {
            "api_key": "",
            "default_mods_path": "",
            "auto_backup": True,
            "max_concurrent_downloads": 3,
            "timeout": 30,
            "retry_count": 3,
            "download_cache": str(self.config_dir / "cache"),
            "last_updated": None
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    # Merge with defaults for any missing keys
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
            except Exception as e:
                logger.warning(f"Error loading config: {e}")
        
        return default_config
    
    def save_config(self):
        """Save configuration to file"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def get(self, key: str, default=None):
        """Get configuration value"""
        return self.config.get(key, default)
    
    def set(self, key: str, value):
        """Set configuration value"""
        self.config[key] = value
        self.save_config()

class MinecraftPathDetector:
    """Detects Minecraft installation paths"""
    
    @staticmethod
    def detect_minecraft_paths() -> List[Path]:
        """Detect possible Minecraft installation paths"""
        system = platform.system()
        paths = []
        
        if system in DEFAULT_MINECRAFT_PATHS:
            for path_str in DEFAULT_MINECRAFT_PATHS[system]:
                path = Path(path_str)
                if path.exists():
                    paths.append(path)
        
        return paths
    
    @staticmethod
    def find_mods_directories() -> List[Path]:
        """Find all mods directories in Minecraft installations"""
        minecraft_paths = MinecraftPathDetector.detect_minecraft_paths()
        mods_dirs = []
        
        for mc_path in minecraft_paths:
            # Standard mods directory
            mods_dir = mc_path / "mods"
            if mods_dir.exists():
                mods_dirs.append(mods_dir)
            
            # Check for profiles/instances
            for subdir in ["profiles", "instances", "versions"]:
                profile_dir = mc_path / subdir
                if profile_dir.exists():
                    for profile in profile_dir.iterdir():
                        if profile.is_dir():
                            profile_mods = profile / "mods"
                            if profile_mods.exists():
                                mods_dirs.append(profile_mods)
        
        return mods_dirs

class CurseForgeAPI:
    """Enhanced CurseForge API client"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.base_url = "https://api.curseforge.com/v1"
        self.api_key = api_key
        self.session = requests.Session()
        
        if api_key:
            self.session.headers.update({
                'x-api-key': api_key,
                'Accept': 'application/json'
            })
        
        self.session.headers.update({
            'User-Agent': 'Qwikee/2.0 (Quick Minecraft Mod Installer)'
        })
    
    def search_mods(self, query: str, page_size: int = 20, game_version: str = None) -> List[Dict]:
        """Search for mods on CurseForge"""
        params = {
            'gameId': 432,  # Minecraft
            'classId': 6,   # Mods
            'searchFilter': query,
            'pageSize': page_size,
            'sortField': 2,  # Popularity
            'sortOrder': 'desc'
        }
        
        if game_version:
            params['gameVersion'] = game_version
        
        try:
            response = self.session.get(f"{self.base_url}/mods/search", params=params)
            response.raise_for_status()
            return response.json().get('data', [])
        except Exception as e:
            logger.error(f"Error searching mods: {e}")
            return []
    
    def get_mod_info(self, mod_id: int) -> Optional[Dict]:
        """Get detailed mod information"""
        try:
            response = self.session.get(f"{self.base_url}/mods/{mod_id}")
            response.raise_for_status()
            return response.json()['data']
        except Exception as e:
            logger.error(f"Error fetching mod info: {e}")
            return None
    
    def get_mod_files(self, mod_id: int, game_version: str = None) -> List[Dict]:
        """Get files for a mod"""
        params = {}
        if game_version:
            params['gameVersion'] = game_version
        
        try:
            response = self.session.get(f"{self.base_url}/mods/{mod_id}/files", params=params)
            response.raise_for_status()
            return response.json().get('data', [])
        except Exception as e:
            logger.error(f"Error fetching mod files: {e}")
            return []
    
    def get_file_info(self, mod_id: int, file_id: int) -> Optional[Dict]:
        """Get specific file information"""
        try:
            response = self.session.get(f"{self.base_url}/mods/{mod_id}/files/{file_id}")
            response.raise_for_status()
            return response.json()['data']
        except Exception as e:
            logger.error(f"Error fetching file info: {e}")
            return None
    
    def get_download_url(self, mod_id: int, file_id: int) -> Optional[str]:
        """Get download URL for a file"""
        try:
            response = self.session.get(f"{self.base_url}/mods/{mod_id}/files/{file_id}/download-url")
            response.raise_for_status()
            return response.json()['data']
        except Exception as e:
            # Fallback to constructed URL
            return f"https://edge.forgecdn.net/files/{str(file_id)[:4]}/{str(file_id)[4:]}/"
    
    def extract_ids_from_url(self, url: str) -> Tuple[Optional[int], Optional[int]]:
        """Extract mod ID and file ID from CurseForge URL"""
        patterns = [
            r'curseforge\.com/minecraft/mc-mods/[^/]+/files/(\d+)',
            r'curseforge\.com/minecraft/mc-mods/[^/]+/download/(\d+)',
            r'curseforge\.com/projects/(\d+)/files/(\d+)',
            r'curseforge\.com/projects/(\d+)',
            r'curseforge\.com/minecraft/mc-mods/([^/]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                groups = match.groups()
                if len(groups) == 1:
                    if groups[0].isdigit():
                        return int(groups[0]), None
                    else:
                        # Handle mod slug - would need to search for it
                        return None, None
                else:
                    return int(groups[0]), int(groups[1])
        
        return None, None

class QwikeeInstaller:
    """Qwikee mod installer with enhanced features"""
    
    def __init__(self, config_manager: QwikeeConfig):
        self.config = config_manager
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Qwikee/2.0'
        })
        
        # Initialize CurseForge API
        api_key = self.config.get('api_key')
        self.cf_api = CurseForgeAPI(api_key)
        
        # Create cache directory
        self.cache_dir = Path(self.config.get('download_cache'))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def parse_modlist(self, file_path: str) -> List[Dict]:
        """Parse modlist file with better error handling"""
        mods = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return []
        
        # Support multiple formats
        if file_path.endswith('.json'):
            try:
                data = json.loads(content)
                if isinstance(data, dict) and 'mods' in data:
                    mods = data['mods']
                elif isinstance(data, list):
                    mods = data
                else:
                    logger.error("Invalid JSON format")
                    return []
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
                return []
        else:
            # Text format
            lines = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')]
            for line_num, line in enumerate(lines, 1):
                mod_info = self.parse_mod_line(line, line_num)
                if mod_info:
                    mods.append(mod_info)
        
        return mods
    
    def parse_mod_line(self, line: str, line_num: int) -> Optional[Dict]:
        """Parse a single mod line from modlist"""
        # Check if it's a CurseForge URL
        if 'curseforge.com' in line.lower():
            mod_id, file_id = self.cf_api.extract_ids_from_url(line)
            return {
                'type': 'curseforge',
                'url': line,
                'mod_id': mod_id,
                'file_id': file_id,
                'line': line_num
            }
        
        # Check if it's JSON format in text
        if line.startswith('{') and line.endswith('}'):
            try:
                mod_data = json.loads(line)
                mod_data['line'] = line_num
                return mod_data
            except json.JSONDecodeError:
                pass
        
        # Direct URL
        if line.startswith('http'):
            return {
                'type': 'direct',
                'url': line,
                'line': line_num
            }
        
        logger.warning(f"Could not parse line {line_num}: {line}")
        return None
    
    def get_filename_from_url(self, url: str) -> str:
        """Enhanced filename extraction"""
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        
        # Try to get filename from Content-Disposition header
        if not filename or not filename.endswith('.jar'):
            try:
                response = self.session.head(url, allow_redirects=True, timeout=10)
                if 'Content-Disposition' in response.headers:
                    content_disp = response.headers['Content-Disposition']
                    filename_match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)', content_disp)
                    if filename_match:
                        filename = filename_match.group(1).strip('"\'')
            except Exception as e:
                logger.debug(f"Could not get filename from headers: {e}")
        
        # Generate filename if still not found
        if not filename or not filename.endswith('.jar'):
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"mod_{url_hash}.jar"
        
        return filename
    
    def download_file(self, url: str, destination: str, description: str = "", 
                     expected_size: Optional[int] = None, 
                     expected_hash: Optional[str] = None) -> bool:
        """Enhanced file download with resume capability and verification"""
        
        destination_path = Path(destination)
        temp_destination = destination_path.with_suffix('.tmp')
        
        # Check if file already exists and is valid
        if destination_path.exists():
            if expected_size and destination_path.stat().st_size == expected_size:
                if expected_hash:
                    if self.verify_file_hash(destination_path, expected_hash):
                        logger.info(f"File already exists and is valid: {destination_path.name}")
                        return True
                else:
                    logger.info(f"File already exists: {destination_path.name}")
                    return True
        
        # Resume download if temp file exists
        resume_header = {}
        if temp_destination.exists():
            resume_header['Range'] = f'bytes={temp_destination.stat().st_size}-'
        
        try:
            response = self.session.get(url, headers=resume_header, stream=True, 
                                      timeout=self.config.get('timeout', 30))
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            if resume_header and response.status_code == 206:
                # Partial content
                existing_size = temp_destination.stat().st_size
                total_size += existing_size
                mode = 'ab'
            else:
                mode = 'wb'
                existing_size = 0
            
            with Progress(
                SpinnerColumn(),
                TextColumn(f"[bold blue]{description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                
                task = progress.add_task("Downloading", total=total_size)
                progress.update(task, advance=existing_size)
                
                with open(temp_destination, mode) as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))
            
            # Verify download
            if expected_size and temp_destination.stat().st_size != expected_size:
                logger.error(f"File size mismatch: expected {expected_size}, got {temp_destination.stat().st_size}")
                return False
            
            if expected_hash and not self.verify_file_hash(temp_destination, expected_hash):
                logger.error("File hash verification failed")
                return False
            
            # Move temp file to final destination
            temp_destination.replace(destination_path)
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Download failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during download: {e}")
            return False
    
    def verify_file_hash(self, file_path: Path, expected_hash: str) -> bool:
        """Verify file hash (SHA1)"""
        try:
            sha1_hash = hashlib.sha1()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha1_hash.update(chunk)
            
            calculated_hash = sha1_hash.hexdigest()
            return calculated_hash.lower() == expected_hash.lower()
        except Exception as e:
            logger.error(f"Error verifying hash: {e}")
            return False
    
    def process_curseforge_mod(self, mod_info: Dict) -> Optional[ModInfo]:
        """Process CurseForge mod with enhanced error handling"""
        mod_id = mod_info.get('mod_id')
        file_id = mod_info.get('file_id')
        
        if not mod_id:
            logger.warning("No mod ID found")
            return None
        
        # Get mod information
        mod_data = self.cf_api.get_mod_info(mod_id)
        if not mod_data:
            logger.error(f"Could not fetch mod info for ID {mod_id}")
            return None
        
        # Get file information
        if file_id:
            file_data = self.cf_api.get_file_info(mod_id, file_id)
        else:
            # Get latest file
            files = self.cf_api.get_mod_files(mod_id)
            if not files:
                logger.error(f"No files found for mod {mod_id}")
                return None
            file_data = files[0]  # Latest file
            file_id = file_data['id']
        
        if not file_data:
            logger.error(f"Could not fetch file info for mod {mod_id}, file {file_id}")
            return None
        
        # Get download URL
        download_url = self.cf_api.get_download_url(mod_id, file_id)
        if not download_url:
            logger.error(f"Could not get download URL for mod {mod_id}, file {file_id}")
            return None
        
        # Extract Minecraft versions
        minecraft_versions = [gv.get('versionString') for gv in file_data.get('gameVersions', [])]
        
        return ModInfo(
            name=mod_data.get('name', 'Unknown Mod'),
            filename=file_data.get('fileName', f"mod_{file_id}.jar"),
            download_url=download_url,
            file_size=file_data.get('fileLength'),
            mod_id=mod_id,
            file_id=file_id,
            version=file_data.get('displayName', ''),
            minecraft_versions=minecraft_versions,
            description=mod_data.get('summary', ''),
            sha1_hash=file_data.get('hashes', [{}])[0].get('value') if file_data.get('hashes') else None
        )
    
    def backup_existing_mods(self, mods_dir: Path) -> Optional[Path]:
        """Create backup of existing mods"""
        if not self.config.get('auto_backup', True):
            return None
        
        backup_dir = mods_dir.parent / f"mods_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        try:
            if mods_dir.exists() and any(mods_dir.iterdir()):
                shutil.copytree(mods_dir, backup_dir)
                logger.info(f"Created backup at: {backup_dir}")
                return backup_dir
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
        
        return None
    
    def install_mods(self, mods: List[Dict], mods_path: Path, 
                    force: bool = False, dry_run: bool = False) -> Dict[str, int]:
        """Install mods with enhanced error handling and statistics"""
        
        results = {'successful': 0, 'failed': 0, 'skipped': 0}
        
        # Create mods directory if it doesn't exist
        if not dry_run:
            mods_path.mkdir(parents=True, exist_ok=True)
            
            # Create backup
            backup_path = self.backup_existing_mods(mods_path)
            if backup_path:
                logger.info(f"Backup created at: {backup_path}")
        
        # Process each mod
        for mod_data in mods:
            try:
                mod_info = None
                
                if mod_data['type'] == 'curseforge':
                    mod_info = self.process_curseforge_mod(mod_data)
                elif mod_data['type'] == 'direct':
                    filename = self.get_filename_from_url(mod_data['url'])
                    mod_info = ModInfo(
                        name=filename,
                        filename=filename,
                        download_url=mod_data['url']
                    )
                
                if not mod_info:
                    logger.error(f"Failed to process mod from line {mod_data.get('line', 'unknown')}")
                    results['failed'] += 1
                    continue
                
                destination = mods_path / mod_info.filename
                
                # Check if file already exists
                if destination.exists() and not force:
                    if not Confirm.ask(f"File [bold]{mod_info.filename}[/bold] exists. Overwrite?"):
                        logger.info(f"Skipped: {mod_info.name}")
                        results['skipped'] += 1
                        continue
                
                if dry_run:
                    logger.info(f"Would download: {mod_info.name}")
                    results['successful'] += 1
                    continue
                
                # Download the mod
                success = self.download_file(
                    mod_info.download_url,
                    str(destination),
                    mod_info.name,
                    mod_info.file_size,
                    mod_info.sha1_hash
                )
                
                if success:
                    logger.info(f"✅ Installed: {mod_info.name}")
                    results['successful'] += 1
                else:
                    logger.error(f"❌ Failed: {mod_info.name}")
                    results['failed'] += 1
                
                # Be respectful to servers
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error processing mod: {e}")
                results['failed'] += 1
        
        return results

# CLI Commands
@click.group(context_settings={'help_option_names': ['-h', '--help']})
@click.version_option(version="2.0.0")
def cli():
    """🚀 Qwikee - Quick Minecraft Mod Installer
    
    A comprehensive tool for downloading and installing Minecraft mods
    from CurseForge and direct URLs with lightning speed and ease.
    """
    pass

@cli.command()
@click.option('--api-key', help='CurseForge API key')
@click.option('--mods-path', help='Default mods directory path')
@click.option('--auto-backup/--no-auto-backup', default=True, help='Enable/disable automatic backups')
@click.option('--timeout', type=int, default=30, help='Download timeout in seconds')
@click.option('--max-downloads', type=int, default=3, help='Maximum concurrent downloads')
def config(api_key, mods_path, auto_backup, timeout, max_downloads):
    """⚙️ Configure Qwikee settings"""
    config_manager = QwikeeConfig()
    
    if api_key:
        config_manager.set('api_key', api_key)
        console.print("✅ API key saved")
    
    if mods_path:
        config_manager.set('default_mods_path', mods_path)
        console.print(f"✅ Default mods path set to: {mods_path}")
    
    config_manager.set('auto_backup', auto_backup)
    config_manager.set('timeout', timeout)
    config_manager.set('max_concurrent_downloads', max_downloads)
    
    console.print("✅ Configuration saved")

@cli.command()
@click.argument('modlist', type=click.Path(exists=True))
@click.option('--mods-path', '-p', help='Path to mods directory')
@click.option('--force', '-f', is_flag=True, help='Overwrite existing files')
@click.option('--dry-run', is_flag=True, help='Show what would be downloaded')
@click.option('--backup/--no-backup', default=True, help='Create backup before installing')
def install(modlist, mods_path, force, dry_run, backup):
    """📦 Install mods from a modlist file"""
    config_manager = QwikeeConfig()
    installer = QwikeeInstaller(config_manager)
    
    # Show header
    console.print(Panel.fit(
        "[bold blue]🚀 Qwikee - Quick Minecraft Mod Installer v2.0[/bold blue]\n"
        "[dim]Lightning-fast mod installation with advanced features[/dim]",
        border_style="blue"
    ))
    
    # Parse modlist
    console.print(f"📖 Reading modlist from: [bold]{modlist}[/bold]")
    mods = installer.parse_modlist(modlist)
    
    if not mods:
        console.print("[red]❌ No valid mods found in modlist file[/red]")
        return
    
    console.print(f"✅ Found [bold green]{len(mods)}[/bold green] mod(s) to process")
    
    # Determine mods path
    if not mods_path:
        mods_path = config_manager.get('default_mods_path')
        
        if not mods_path:
            # Auto-detect Minecraft paths
            detected_paths = MinecraftPathDetector.find_mods_directories()
            
            if detected_paths:
                console.print("\n📁 Detected Minecraft mod directories:")
                for i, path in enumerate(detected_paths, 1):
                    console.print(f"  {i}. {path}")
                
                if len(detected_paths) == 1:
                    mods_path = str(detected_paths[0])
                else:
                    choice = Prompt.ask(
                        f"Select directory (1-{len(detected_paths)})", 
                        default="1"
                    )
                    try:
                        mods_path = str(detected_paths[int(choice) - 1])
                    except (ValueError, IndexError):
                        mods_path = str(detected_paths[0])
            else:
                # Fallback to desktop
                desktop_path = Path.home() / "Desktop" / "MinecraftMods"
                mods_path = str(desktop_path)
                console.print(f"⚠️  No Minecraft installation detected. Using: [bold]{mods_path}[/bold]")
    
    mods_path = Path(mods_path)
    console.print(f"📂 Installing to: [bold]{mods_path}[/bold]")
    
    # Install mods
    if dry_run:
        console.print("\n[yellow]🔍 Dry run mode - no files will be downloaded[/yellow]")
    
    results = installer.install_mods(mods, mods_path, force, dry_run)
    
    # Show results
    console.print(Panel.fit(
        f"[bold green]✅ Successfully processed: {results['successful']} mod(s)[/bold green]\n"
        f"[bold red]❌ Failed: {results['failed']} mod(s)[/bold red]\n"
        f"[bold yellow]⏭️  Skipped: {results['skipped']} mod(s)[/bold yellow]\n"
        f"[dim]📂 Location: {mods_path}[/dim]",
        title="📊 Installation Complete",
        border_style="green"
    ))

@cli.command()
@click.argument('query')
@click.option('--limit', '-l', default=10, help='Number of results to show')
@click.option('--game-version', '-v', help='Filter by Minecraft version')
@click.option('--output', '-o', type=click.Path(), help='Save results to file')
def search(query, limit, game_version, output):
    """🔍 Search for mods on CurseForge"""
    config_manager = QwikeeConfig()
    api_key = config_manager.get('api_key')
    
    if not api_key:
        console.print("[red]❌ CurseForge API key required for search[/red]")
        console.print("[dim]Run: qwikee config --api-key YOUR_KEY[/dim]")
        return
    
    cf_api = CurseForgeAPI(api_key)
    
    with Status(f"[bold green]Searching for '{query}'...") as status:
        results = cf_api.search_mods(query, limit, game_version)
    
    if not results:
        console.print("[yellow]No mods found matching your search[/yellow]")
        return
    
    # Display results
    table = Table(title=f"🔍 Search Results for '{query}'")
    table.add_column("Name", style="bold green")
    table.add_column("Author", style="yellow")
    table.add_column("Downloads", style="magenta")
    table.add_column("Latest Version", style="blue")
    
    for mod in results:
        author = mod['authors'][0]['name'] if mod['authors'] else 'Unknown'
        downloads = f"{mod['downloadCount']:,}"
        latest_version = mod.get('latestFiles', [{}])[0].get('displayName', 'N/A')
        
        table.add_row(
            mod['name'],
            author,
            downloads,
            latest_version
        )
    
    console.print(table)
    
    # Save results if requested
    if output:
        urls = []
        for mod in results:
            urls.append(f"https://www.curseforge.com/minecraft/mc-mods/{mod['slug']}")
        
        try:
            with open(output, 'w') as f:
                f.write(f"# Search results for '{query}'\n")
                f.write(f"# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                for url in urls:
                    f.write(f"{url}\n")
            
            console.print(f"💾 Results saved to: [bold]{output}[/bold]")
        except Exception as e:
            console.print(f"[red]Error saving file: {e}[/red]")

@cli.command()
def detect():
    """🔍 Detect Minecraft installations and mod directories"""
    console.print("[bold blue]🔍 Detecting Minecraft installations...[/bold blue]\n")
    
    # Detect Minecraft paths
    mc_paths = MinecraftPathDetector.detect_minecraft_paths()
    if mc_paths:
        console.print("📦 Minecraft installations found:")
        for path in mc_paths:
            console.print(f"  • {path}")
    else:
        console.print("❌ No Minecraft installations detected")
    
    # Detect mod directories
    mod_dirs = MinecraftPathDetector.find_mods_directories()
    if mod_dirs:
        console.print("\n📁 Mod directories found:")
        for mod_dir in mod_dirs:
            mod_count = len([f for f in mod_dir.iterdir() if f.suffix == '.jar'])
            console.print(f"  • {mod_dir} ({mod_count} mods)")
    else:
        console.print("\n❌ No mod directories found")

if __name__ == '__main__':
    cli()
