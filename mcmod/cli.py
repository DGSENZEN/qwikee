#!/usr/bin/env python3
"""
Minecraft Mod Manager CLI
A tool to search, stage, and install Minecraft mods and manage mod loaders
"""

import os
import json
import shutil
import asyncio
import zipfile
import subprocess
import platform
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, asdict
from urllib.parse import quote
from datetime import datetime, timedelta

import click
import httpx
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, DownloadColumn, BarColumn, TaskID, MofNCompleteColumn
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.live import Live
from rich.status import Status

console = Console()

# Configuration
CONFIG_DIR = Path.home() / ".minecraft-mod-manager"
STAGING_FILE = CONFIG_DIR / "staging.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOADER_CACHE_FILE = CONFIG_DIR / "loader_cache.json"
INSTALLED_MODS_FILE = CONFIG_DIR / "installed_mods.json"
MODPACK_HISTORY_FILE = CONFIG_DIR / "modpack_history.json"
MODRINTH_API_BASE = "https://api.modrinth.com/v2"

# Mod Loader APIs
FABRIC_API_BASE = "https://meta.fabricmc.net/v2"
FORGE_API_BASE = "https://files.minecraftforge.net/net/minecraftforge/forge"
QUILT_API_BASE = "https://meta.quiltmc.org/v3"

# Rate limiting
API_RATE_LIMIT = 300  # requests per minute
API_RATE_DELAY = 60 / API_RATE_LIMIT  # seconds between requests

# Update check interval
UPDATE_CHECK_INTERVAL = timedelta(hours=6)


@dataclass
class ModInfo:
    """Represents a Minecraft mod"""
    id: str
    name: str
    description: str
    author: str
    downloads: int
    categories: List[str]
    game_versions: List[str]
    download_url: str
    filename: str
    mod_loader: str = "fabric"
    file_size: int = 0
    project_url: str = ""
    version_id: str = ""
    version_number: str = ""
    file_hash: str = ""
    last_updated: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "ModInfo":
        return cls(**data)


@dataclass
class InstalledMod:
    """Represents an installed mod"""
    filename: str
    name: str
    version: str
    mod_id: str
    author: str
    description: str
    mod_loader: str
    file_size: int
    file_hash: str = ""
    install_date: str = ""
    source_url: str = ""
    version_id: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "InstalledMod":
        # Handle missing fields for backward compatibility
        fields = cls.__dataclass_fields__.keys()
        filtered_data = {k: v for k, v in data.items() if k in fields}
        # Set defaults for missing fields
        for field in fields:
            if field not in filtered_data:
                if field == "file_hash":
                    filtered_data[field] = ""
                elif field == "install_date":
                    filtered_data[field] = ""
                elif field == "source_url":
                    filtered_data[field] = ""
                elif field == "version_id":
                    filtered_data[field] = ""
        return cls(**filtered_data)


@dataclass
class ModLoaderInfo:
    """Represents a mod loader version"""
    loader_type: str  # fabric, forge, quilt
    minecraft_version: str
    loader_version: str
    stable: bool
    download_url: str
    installer_url: str
    release_date: str
    
    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "ModLoaderInfo":
        return cls(**data)


@dataclass
class InstalledLoader:
    """Represents an installed mod loader"""
    loader_type: str
    minecraft_version: str
    loader_version: str
    profile_name: str
    install_path: str
    install_date: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "InstalledLoader":
        fields = cls.__dataclass_fields__.keys()
        filtered_data = {k: v for k, v in data.items() if k in fields}
        if "install_date" not in filtered_data:
            filtered_data["install_date"] = ""
        return cls(**filtered_data)


@dataclass
class ModPack:
    """Represents a modpack"""
    id: str
    name: str
    description: str
    author: str
    downloads: int
    categories: List[str]
    game_versions: List[str]
    mod_loader: str
    mod_count: int
    download_url: str
    filename: str
    version_id: str = ""
    version_number: str = ""
    install_date: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "ModPack":
        fields = cls.__dataclass_fields__.keys()
        filtered_data = {k: v for k, v in data.items() if k in fields}
        for field in ["version_id", "version_number", "install_date"]:
            if field not in filtered_data:
                filtered_data[field] = ""
        return cls(**filtered_data)


@dataclass
class UpdateInfo:
    """Represents available update information"""
    item_type: str  # mod, loader, modpack
    item_id: str
    current_version: str
    new_version: str
    download_url: str
    changelog: str = ""


class FileUtils:
    """Utility functions for file operations"""
    
    @staticmethod
    def calculate_file_hash(file_path: Path) -> str:
        """Calculate SHA256 hash of a file"""
        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception:
            return ""
    
    @staticmethod
    def safe_remove(file_path: Path) -> bool:
        """Safely remove a file"""
        try:
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            console.print(f"[red]Error removing {file_path}: {e}[/red]")
            return False
    
    @staticmethod
    def safe_create_dir(dir_path: Path) -> bool:
        """Safely create a directory"""
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            console.print(f"[red]Error creating directory {dir_path}: {e}[/red]")
            return False
    
    @staticmethod
    def backup_file(file_path: Path, backup_suffix: str = ".backup") -> Optional[Path]:
        """Create a backup of a file"""
        try:
            if file_path.exists():
                backup_path = file_path.with_suffix(file_path.suffix + backup_suffix)
                shutil.copy2(file_path, backup_path)
                return backup_path
            return None
        except Exception as e:
            console.print(f"[red]Error backing up {file_path}: {e}[/red]")
            return None


class RateLimiter:
    """Simple rate limiter for API calls"""
    
    def __init__(self, calls_per_minute: int = 300):
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self.last_call = 0
    
    async def wait(self):
        """Wait if necessary to respect rate limits"""
        now = time.time()
        elapsed = now - self.last_call
        
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            await asyncio.sleep(sleep_time)
        
        self.last_call = time.time()


class ModLoaderManager:
    """Manages mod loaders (Fabric, Forge, Quilt)"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.cache_file = LOADER_CACHE_FILE
        self.cache = self.load_cache()
        self.rate_limiter = RateLimiter()
    
    def load_cache(self) -> Dict:
        """Load loader cache from file"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                console.print(f"[yellow]Warning: Could not load loader cache: {e}[/yellow]")
        return {}
    
    def save_cache(self):
        """Save loader cache to file"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not save loader cache: {e}[/yellow]")
    
    async def get_minecraft_versions(self) -> List[str]:
        """Get available Minecraft versions"""
        cache_key = "minecraft_versions"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            await self.rate_limiter.wait()
            response = await self.client.get(f"{FABRIC_API_BASE}/versions/game")
            response.raise_for_status()
            versions = [v["version"] for v in response.json() if v["stable"]]
            self.cache[cache_key] = versions
            self.save_cache()
            return versions
        except Exception as e:
            console.print(f"[red]Error fetching Minecraft versions: {e}[/red]")
            return []
    
    async def get_fabric_versions(self, minecraft_version: str) -> List[ModLoaderInfo]:
        """Get available Fabric versions"""
        try:
            # Get Fabric loader versions
            await self.rate_limiter.wait()
            loader_response = await self.client.get(f"{FABRIC_API_BASE}/versions/loader")
            loader_response.raise_for_status()
            loaders = loader_response.json()
            
            # Get installer version
            await self.rate_limiter.wait()
            installer_response = await self.client.get(f"{FABRIC_API_BASE}/versions/installer")
            installer_response.raise_for_status()
            installer_version = installer_response.json()[0]["version"]
            
            fabric_versions = []
            for loader in loaders[:15]:  # Limit to 15 recent versions
                loader_version = loader["version"]
                
                fabric_versions.append(ModLoaderInfo(
                    loader_type="fabric",
                    minecraft_version=minecraft_version,
                    loader_version=loader_version,
                    stable=loader["stable"],
                    download_url="",  # Fabric doesn't have direct download
                    installer_url=f"https://maven.fabricmc.net/net/fabricmc/fabric-installer/{installer_version}/fabric-installer-{installer_version}.jar",
                    release_date=loader.get("build_time", "")
                ))
            
            return fabric_versions
        except Exception as e:
            console.print(f"[red]Error fetching Fabric versions: {e}[/red]")
            return []
    
    async def get_forge_versions(self, minecraft_version: str) -> List[ModLoaderInfo]:
        """Get available Forge versions"""
        try:
            # Forge API is more complex, using a simplified approach
            await self.rate_limiter.wait()
            url = f"https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            
            forge_versions = []
            # Get recommended version
            recommended_key = f"{minecraft_version}-recommended"
            latest_key = f"{minecraft_version}-latest"
            
            for key in [recommended_key, latest_key]:
                if key in data["promos"]:
                    forge_version = data["promos"][key]
                    full_version = f"{minecraft_version}-{forge_version}"
                    
                    forge_versions.append(ModLoaderInfo(
                        loader_type="forge",
                        minecraft_version=minecraft_version,
                        loader_version=forge_version,
                        stable=key.endswith("-recommended"),
                        download_url="",
                        installer_url=f"https://maven.minecraftforge.net/net/minecraftforge/forge/{full_version}/forge-{full_version}-installer.jar",
                        release_date=""
                    ))
            
            return forge_versions
        except Exception as e:
            console.print(f"[red]Error fetching Forge versions: {e}[/red]")
            return []
    
    async def get_quilt_versions(self, minecraft_version: str) -> List[ModLoaderInfo]:
        """Get available Quilt versions"""
        try:
            # Get Quilt loader versions
            await self.rate_limiter.wait()
            loader_response = await self.client.get(f"{QUILT_API_BASE}/versions/loader")
            loader_response.raise_for_status()
            loaders = loader_response.json()
            
            # Get installer version
            await self.rate_limiter.wait()
            installer_response = await self.client.get(f"{QUILT_API_BASE}/versions/installer")
            installer_response.raise_for_status()
            installer_version = installer_response.json()[0]["version"]
            
            quilt_versions = []
            for loader in loaders[:15]:  # Limit to 15 recent versions
                loader_version = loader["version"]
                
                quilt_versions.append(ModLoaderInfo(
                    loader_type="quilt",
                    minecraft_version=minecraft_version,
                    loader_version=loader_version,
                    stable=True,  # Quilt doesn't have stability info
                    download_url="",
                    installer_url=f"https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/{installer_version}/quilt-installer-{installer_version}.jar",
                    release_date=""
                ))
            
            return quilt_versions
        except Exception as e:
            console.print(f"[red]Error fetching Quilt versions: {e}[/red]")
            return []
    
    async def download_installer(self, loader_info: ModLoaderInfo, download_path: Path) -> bool:
        """Download mod loader installer"""
        try:
            console.print(f"[blue]Downloading {loader_info.loader_type} installer...[/blue]")
            
            await self.rate_limiter.wait()
            response = await self.client.get(loader_info.installer_url)
            response.raise_for_status()
            
            with open(download_path, 'wb') as f:
                f.write(response.content)
            
            console.print(f"[green]✓[/green] Downloaded installer to {download_path}")
            return True
        except Exception as e:
            console.print(f"[red]Error downloading installer: {e}[/red]")
            return False
    
    def get_minecraft_dir(self) -> Path:
        """Get the Minecraft directory based on OS"""
        system = platform.system()
        if system == "Windows":
            return Path(os.getenv("APPDATA")) / ".minecraft"
        elif system == "Darwin":  # macOS
            return Path.home() / "Library" / "Application Support" / "minecraft"
        else:  # Linux
            return Path.home() / ".minecraft"
    
    def detect_installed_loaders(self) -> List[InstalledLoader]:
        """Detect installed mod loaders"""
        minecraft_dir = self.get_minecraft_dir()
        versions_dir = minecraft_dir / "versions"
        
        if not versions_dir.exists():
            return []
        
        installed_loaders = []
        
        try:
            for version_dir in versions_dir.iterdir():
                if version_dir.is_dir():
                    json_file = version_dir / f"{version_dir.name}.json"
                    if json_file.exists():
                        try:
                            with open(json_file, 'r') as f:
                                version_data = json.load(f)
                            
                            # Detect loader type based on version data
                            loader_type = "vanilla"
                            if "fabric" in version_data.get("id", "").lower():
                                loader_type = "fabric"
                            elif "forge" in version_data.get("id", "").lower():
                                loader_type = "forge"
                            elif "quilt" in version_data.get("id", "").lower():
                                loader_type = "quilt"
                            
                            if loader_type != "vanilla":
                                # Get install date from file modification time
                                install_date = datetime.fromtimestamp(json_file.stat().st_mtime).isoformat()
                                
                                installed_loaders.append(InstalledLoader(
                                    loader_type=loader_type,
                                    minecraft_version=version_data.get("inheritsFrom", "unknown"),
                                    loader_version="unknown",
                                    profile_name=version_dir.name,
                                    install_path=str(version_dir),
                                    install_date=install_date
                                ))
                        except Exception as e:
                            console.print(f"[dim]Warning: Could not parse {json_file}: {e}[/dim]")
                            continue
        except Exception as e:
            console.print(f"[red]Error scanning loader installations: {e}[/red]")
        
        return installed_loaders
    
    async def install_loader(self, loader_info: ModLoaderInfo, minecraft_dir: Path) -> bool:
        """Install a mod loader"""
        installer_path = CONFIG_DIR / f"{loader_info.loader_type}-installer.jar"
        
        # Download installer
        if not await self.download_installer(loader_info, installer_path):
            return False
        
        # Run installer
        try:
            console.print(f"[blue]Installing {loader_info.loader_type} {loader_info.loader_version}...[/blue]")
            
            # Prepare installation command
            if loader_info.loader_type == "fabric":
                cmd = [
                    "java", "-jar", str(installer_path), "client",
                    "-mcversion", loader_info.minecraft_version,
                    "-loader", loader_info.loader_version,
                    "-dir", str(minecraft_dir)
                ]
            elif loader_info.loader_type == "forge":
                cmd = [
                    "java", "-jar", str(installer_path),
                    "--installClient", str(minecraft_dir)
                ]
            elif loader_info.loader_type == "quilt":
                cmd = [
                    "java", "-jar", str(installer_path), "install", "client",
                    loader_info.minecraft_version, loader_info.loader_version,
                    "--install-dir", str(minecraft_dir)
                ]
            else:
                console.print(f"[red]Unknown loader type: {loader_info.loader_type}[/red]")
                return False
            
            # Run installation
            with Status(f"Installing {loader_info.loader_type}...", spinner="dots"):
                result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                console.print(f"[green]✓[/green] Successfully installed {loader_info.loader_type} {loader_info.loader_version}")
                return True
            else:
                console.print(f"[red]Installation failed: {result.stderr}[/red]")
                return False
                
        except Exception as e:
            console.print(f"[red]Error installing loader: {e}[/red]")
            return False
        finally:
            # Clean up installer
            FileUtils.safe_remove(installer_path)
    
    def uninstall_loader(self, loader: InstalledLoader) -> bool:
        """Uninstall a mod loader"""
        try:
            install_path = Path(loader.install_path)
            if install_path.exists():
                shutil.rmtree(install_path)
                console.print(f"[green]✓[/green] Uninstalled {loader.loader_type} profile: {loader.profile_name}")
                return True
            else:
                console.print(f"[yellow]Profile directory not found: {install_path}[/yellow]")
                return False
        except Exception as e:
            console.print(f"[red]Error uninstalling loader: {e}[/red]")
            return False
    
    def clean_all_loaders(self, minecraft_dir: Path) -> int:
        """Clean all mod loader installations"""
        try:
            versions_dir = minecraft_dir / "versions"
            if not versions_dir.exists():
                return 0
            
            removed_count = 0
            for version_dir in versions_dir.iterdir():
                if version_dir.is_dir():
                    json_file = version_dir / f"{version_dir.name}.json"
                    if json_file.exists():
                        try:
                            with open(json_file, 'r') as f:
                                version_data = json.load(f)
                            
                            # Check if it's a modded profile
                            version_id = version_data.get("id", "").lower()
                            if any(loader in version_id for loader in ["fabric", "forge", "quilt"]):
                                shutil.rmtree(version_dir)
                                removed_count += 1
                        except Exception:
                            continue
            
            return removed_count
        except Exception as e:
            console.print(f"[red]Error cleaning loaders: {e}[/red]")
            return 0
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


class ModParser:
    """Handles parsing mod files to extract metadata"""
    
    @staticmethod
    def parse_mod_file(file_path: Path) -> Optional[InstalledMod]:
        """Parse a mod file and extract metadata"""
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_file:
                # Try Fabric first
                fabric_mod = ModParser._parse_fabric_mod(zip_file, file_path)
                if fabric_mod:
                    return fabric_mod
                
                # Try Forge
                forge_mod = ModParser._parse_forge_mod(zip_file, file_path)
                if forge_mod:
                    return forge_mod
                
                # Try legacy mcmod.info
                legacy_mod = ModParser._parse_legacy_mod(zip_file, file_path)
                if legacy_mod:
                    return legacy_mod
                
        except Exception as e:
            console.print(f"[dim]Warning: Could not parse {file_path.name}: {e}[/dim]")
        
        # Fallback to filename-based info
        return ModParser._create_fallback_mod(file_path)
    
    @staticmethod
    def _parse_fabric_mod(zip_file: zipfile.ZipFile, file_path: Path) -> Optional[InstalledMod]:
        """Parse Fabric mod metadata"""
        try:
            with zip_file.open('fabric.mod.json') as f:
                data = json.load(f)
                
                authors = data.get('authors', [])
                if isinstance(authors, list):
                    author = ', '.join(str(a) for a in authors[:2])
                else:
                    author = str(authors)
                
                return InstalledMod(
                    filename=file_path.name,
                    name=data.get('name', file_path.stem),
                    version=data.get('version', 'Unknown'),
                    mod_id=data.get('id', file_path.stem),
                    author=author or 'Unknown',
                    description=data.get('description', 'No description'),
                    mod_loader='fabric',
                    file_size=file_path.stat().st_size,
                    file_hash=FileUtils.calculate_file_hash(file_path),
                    install_date=datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                )
        except (KeyError, json.JSONDecodeError):
            pass
        return None
    
    @staticmethod
    def _parse_forge_mod(zip_file: zipfile.ZipFile, file_path: Path) -> Optional[InstalledMod]:
        """Parse Forge mod metadata"""
        try:
            # Try modern Forge (mods.toml)
            with zip_file.open('META-INF/mods.toml') as f:
                content = f.read().decode('utf-8')
                # Simple TOML parsing for the basic fields we need
                mod_data = ModParser._parse_simple_toml(content)
                
                if mod_data:
                    return InstalledMod(
                        filename=file_path.name,
                        name=mod_data.get('displayName', file_path.stem),
                        version=mod_data.get('version', 'Unknown'),
                        mod_id=mod_data.get('modId', file_path.stem),
                        author=mod_data.get('authors', 'Unknown'),
                        description=mod_data.get('description', 'No description'),
                        mod_loader='forge',
                        file_size=file_path.stat().st_size,
                        file_hash=FileUtils.calculate_file_hash(file_path),
                        install_date=datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                    )
        except (KeyError, UnicodeDecodeError):
            pass
        return None
    
    @staticmethod
    def _parse_legacy_mod(zip_file: zipfile.ZipFile, file_path: Path) -> Optional[InstalledMod]:
        """Parse legacy mcmod.info"""
        try:
            with zip_file.open('mcmod.info') as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    mod_info = data[0]
                    return InstalledMod(
                        filename=file_path.name,
                        name=mod_info.get('name', file_path.stem),
                        version=mod_info.get('version', 'Unknown'),
                        mod_id=mod_info.get('modid', file_path.stem),
                        author=mod_info.get('authorList', ['Unknown'])[0] if mod_info.get('authorList') else 'Unknown',
                        description=mod_info.get('description', 'No description'),
                        mod_loader='forge',
                        file_size=file_path.stat().st_size,
                        file_hash=FileUtils.calculate_file_hash(file_path),
                        install_date=datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                    )
        except (KeyError, json.JSONDecodeError):
            pass
        return None
    
    @staticmethod
    def _parse_simple_toml(content: str) -> Dict:
        """Simple TOML parser for basic mod metadata"""
        data = {}
        for line in content.split('\n'):
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                data[key] = value
        return data
    
    @staticmethod
    def _create_fallback_mod(file_path: Path) -> InstalledMod:
        """Create mod info from filename when parsing fails"""
        return InstalledMod(
            filename=file_path.name,
            name=file_path.stem,
            version='Unknown',
            mod_id=file_path.stem.lower(),
            author='Unknown',
            description='No description available',
            mod_loader='unknown',
            file_size=file_path.stat().st_size,
            file_hash=FileUtils.calculate_file_hash(file_path),
            install_date=datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
        )


class ModManager:
    """Handles mod operations and staging"""
    
    def __init__(self):
        self.config_dir = CONFIG_DIR
        self.staging_file = STAGING_FILE
        self.config_file = CONFIG_FILE
        self.installed_mods_file = INSTALLED_MODS_FILE
        self.ensure_config_dir()
        self.load_config()
    
    def ensure_config_dir(self):
        """Create config directory if it doesn't exist"""
        FileUtils.safe_create_dir(self.config_dir)
    
    def load_config(self):
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            except Exception as e:
                console.print(f"[yellow]Warning: Could not load config: {e}[/yellow]")
                self.config = self._get_default_config()
        else:
            self.config = self._get_default_config()
            self.save_config()
        
        # Ensure mod_directory is always a string
        if isinstance(self.config.get("mod_directory"), Path):
            self.config["mod_directory"] = str(self.config["mod_directory"])
            self.save_config()
    
    def _get_default_config(self) -> Dict:
        """Get default configuration"""
        return {
            "mod_directory": str(Path.home() / ".minecraft" / "mods"),
            "minecraft_version": "1.20.1",
            "mod_loader": "fabric",
            "backup_enabled": True,
            "auto_update_check": True,
            "last_update_check": ""
        }
    
    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            console.print(f"[red]Error saving config: {e}[/red]")
    
    def ensure_mod_directory_exists(self) -> bool:
        """Ensure mod directory exists and is accessible"""
        mod_directory = self.config["mod_directory"]
        if isinstance(mod_directory, Path):
            mod_directory = str(mod_directory)
            self.config["mod_directory"] = mod_directory
            self.save_config()
        
        mod_dir = Path(mod_directory)
        
        if not mod_dir.exists():
            console.print(f"[yellow]Mod directory does not exist: {mod_dir}[/yellow]")
            if Confirm.ask("Create the mod directory?"):
                return FileUtils.safe_create_dir(mod_dir)
            else:
                return False
        
        # Check if directory is writable
        if not os.access(mod_dir, os.W_OK):
            console.print(f"[red]Mod directory is not writable: {mod_dir}[/red]")
            return False
        
        return True
    
    def get_staged_mods(self) -> List[ModInfo]:
        """Get list of staged mods"""
        if not self.staging_file.exists():
            return []
        
        try:
            with open(self.staging_file, 'r') as f:
                data = json.load(f)
                return [ModInfo.from_dict(mod) for mod in data]
        except Exception as e:
            console.print(f"[red]Error loading staged mods: {e}[/red]")
            return []
    
    def save_staged_mods(self, mods: List[ModInfo]):
        """Save staged mods to file"""
        try:
            with open(self.staging_file, 'w') as f:
                json.dump([mod.to_dict() for mod in mods], f, indent=2)
        except Exception as e:
            console.print(f"[red]Error saving staged mods: {e}[/red]")
    
    def get_installed_mods_record(self) -> List[InstalledMod]:
        """Get installed mods record from file"""
        if not self.installed_mods_file.exists():
            return []
        
        try:
            with open(self.installed_mods_file, 'r') as f:
                data = json.load(f)
                return [InstalledMod.from_dict(mod) for mod in data]
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load installed mods record: {e}[/yellow]")
            return []
    
    def save_installed_mods_record(self, mods: List[InstalledMod]):
        """Save installed mods record to file"""
        try:
            with open(self.installed_mods_file, 'w') as f:
                json.dump([mod.to_dict() for mod in mods], f, indent=2)
        except Exception as e:
            console.print(f"[red]Error saving installed mods record: {e}[/red]")
    
    def add_to_staging(self, mod: ModInfo):
        """Add mod to staging area"""
        staged_mods = self.get_staged_mods()
        
        # Check if mod is already staged
        if any(m.id == mod.id for m in staged_mods):
            console.print(f"[yellow]Mod '{mod.name}' is already staged![/yellow]")
            return False
        
        staged_mods.append(mod)
        self.save_staged_mods(staged_mods)
        console.print(f"[green]✓[/green] Added '{mod.name}' to staging area")
        return True
    
    def add_mods_to_staging(self, mods: List[ModInfo]) -> Tuple[int, int]:
        """Add multiple mods to staging area"""
        staged_mods = self.get_staged_mods()
        staged_ids = {m.id for m in staged_mods}
        
        new_mods = []
        skipped_count = 0
        
        for mod in mods:
            if mod.id not in staged_ids:
                new_mods.append(mod)
                staged_ids.add(mod.id)
            else:
                skipped_count += 1
        
        if new_mods:
            staged_mods.extend(new_mods)
            self.save_staged_mods(staged_mods)
        
        return len(new_mods), skipped_count
    
    def remove_from_staging(self, mod_id: str):
        """Remove mod from staging area"""
        staged_mods = self.get_staged_mods()
        original_count = len(staged_mods)
        staged_mods = [m for m in staged_mods if m.id != mod_id]
        
        if len(staged_mods) < original_count:
            self.save_staged_mods(staged_mods)
            console.print(f"[green]✓[/green] Removed mod from staging area")
            return True
        else:
            console.print(f"[red]✗[/red] Mod not found in staging area")
            return False
    
    def clear_staging(self):
        """Clear all staged mods"""
        self.save_staged_mods([])
        console.print("[green]✓[/green] Cleared staging area")
    
    def get_installed_mods(self) -> List[InstalledMod]:
        """Get list of installed mods by scanning directory"""
        # Ensure mod_directory is a string
        mod_directory = self.config["mod_directory"]
        if isinstance(mod_directory, Path):
            mod_directory = str(mod_directory)
        
        mod_dir = Path(mod_directory)
        
        # Check if directory exists
        if not mod_dir.exists():
            console.print(f"[yellow]Mod directory {mod_dir} does not exist[/yellow]")
            if Confirm.ask("Create the mod directory?"):
                if FileUtils.safe_create_dir(mod_dir):
                    return []
                else:
                    return []
            else:
                return []
        
        # Check if directory is readable
        if not os.access(mod_dir, os.R_OK):
            console.print(f"[red]Cannot read mod directory {mod_dir}[/red]")
            return []
        
        installed_mods = []
        
        try:
            mod_files = list(mod_dir.glob("*.jar"))
        except (OSError, PermissionError) as e:
            console.print(f"[red]Error accessing mod directory {mod_dir}: {e}[/red]")
            return []
        
        if not mod_files:
            return []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True
        ) as progress:
            task = progress.add_task("Scanning mod files...", total=len(mod_files))
            
            for mod_file in mod_files:
                progress.update(task, description=f"Parsing {mod_file.name}...")
                try:
                    mod_info = ModParser.parse_mod_file(mod_file)
                    if mod_info:
                        installed_mods.append(mod_info)
                except Exception as e:
                    console.print(f"[dim]Warning: Could not parse {mod_file.name}: {e}[/dim]")
                progress.advance(task)
        
        # Update installed mods record
        self.save_installed_mods_record(installed_mods)
        
        return installed_mods
    
    def remove_installed_mod(self, filename: str) -> bool:
        """Remove an installed mod"""
        mod_dir = Path(self.config["mod_directory"])
        mod_path = mod_dir / filename
        
        if self.config.get("backup_enabled", True):
            backup_path = FileUtils.backup_file(mod_path)
            if backup_path:
                console.print(f"[blue]Backup created: {backup_path}[/blue]")
        
        return FileUtils.safe_remove(mod_path)
    
    def clean_mods_folder(self) -> int:
        """Clean all mods from the mods folder"""
        mod_dir = Path(self.config["mod_directory"])
        if not mod_dir.exists():
            return 0
        
        try:
            mod_files = list(mod_dir.glob("*.jar"))
            
            if self.config.get("backup_enabled", True) and mod_files:
                backup_dir = mod_dir / "backup"
                FileUtils.safe_create_dir(backup_dir)
                
                for mod_file in mod_files:
                    try:
                        shutil.copy2(mod_file, backup_dir / mod_file.name)
                    except Exception as e:
                        console.print(f"[yellow]Warning: Could not backup {mod_file.name}: {e}[/yellow]")
                
                if backup_dir.exists():
                    console.print(f"[blue]Mods backed up to: {backup_dir}[/blue]")
            
            for mod_file in mod_files:
                FileUtils.safe_remove(mod_file)
            
            # Clear installed mods record
            self.save_installed_mods_record([])
            
            return len(mod_files)
        except Exception as e:
            console.print(f"[red]Error cleaning mods folder: {e}[/red]")
            return 0


class ModrinthAPI:
    """Handles Modrinth API interactions"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=MODRINTH_API_BASE,
            timeout=30.0,
            headers={
                "User-Agent": "minecraft-mod-manager/1.0.0"
            }
        )
        self.rate_limiter = RateLimiter(calls_per_minute=300)
    
    async def search_mods(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for mods on Modrinth"""
        url = f"/search?query={quote(query)}&limit={limit}&facets=%5B%5B%22project_type%3Amod%22%5D%5D"
        
        try:
            await self.rate_limiter.wait()
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("hits", [])
        except httpx.RequestError as e:
            console.print(f"[red]Network error searching mods: {e}[/red]")
            return []
        except httpx.HTTPStatusError as e:
            console.print(f"[red]HTTP error searching mods: {e}[/red]")
            return []
        except Exception as e:
            console.print(f"[red]Unexpected error: {e}[/red]")
            return []
    
    async def search_modpacks(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for modpacks on Modrinth"""
        url = f"/search?query={quote(query)}&limit={limit}&facets=%5B%5B%22project_type%3Amodpack%22%5D%5D"
        
        try:
            await self.rate_limiter.wait()
            response = await self.client.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get("hits", [])
        except httpx.RequestError as e:
            console.print(f"[red]Network error searching modpacks: {e}[/red]")
            return []
        except httpx.HTTPStatusError as e:
            console.print(f"[red]HTTP error searching modpacks: {e}[/red]")
            return []
        except Exception as e:
            console.print(f"[red]Unexpected error: {e}[/red]")
            return []
    
    async def get_mod_by_id(self, mod_id: str) -> Optional[Dict]:
        """Get mod details by ID"""
        try:
            await self.rate_limiter.wait()
            response = await self.client.get(f"/project/{mod_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                console.print(f"[red]Mod not found: {mod_id}[/red]")
            else:
                console.print(f"[red]Error fetching mod {mod_id}: {e}[/red]")
            return None
        except Exception as e:
            console.print(f"[red]Error fetching mod {mod_id}: {e}[/red]")
            return None
    
    async def get_mods_by_ids(self, mod_ids: List[str]) -> List[Dict]:
        """Get multiple mods by their IDs"""
        if not mod_ids:
            return []
        
        try:
            # Batch request for multiple mods
            await self.rate_limiter.wait()
            ids_param = '["' + '","'.join(mod_ids) + '"]'
            response = await self.client.get(f"/projects?ids={quote(ids_param)}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error fetching mods: {e}[/red]")
            return []
        except Exception as e:
            console.print(f"[red]Error fetching mods: {e}[/red]")
            return []
    
    async def get_mod_versions(self, mod_id: str, minecraft_version: str, 
                             mod_loader: str) -> List[Dict]:
        """Get versions for a specific mod"""
        try:
            # Get all versions first
            await self.rate_limiter.wait()
            response = await self.client.get(f"/project/{mod_id}/version")
            response.raise_for_status()
            all_versions = response.json()
            
            # Filter for compatible versions
            compatible_versions = []
            for version in all_versions:
                game_versions = version.get("game_versions", [])
                loaders = version.get("loaders", [])
                
                if (minecraft_version in game_versions and mod_loader in loaders):
                    compatible_versions.append(version)
            
            return compatible_versions
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error getting mod versions: {e}[/red]")
            return []
        except Exception as e:
            console.print(f"[red]Error getting mod versions: {e}[/red]")
            return []
    
    async def get_modpack_details(self, pack_id: str) -> Optional[Dict]:
        """Get modpack details"""
        try:
            await self.rate_limiter.wait()
            response = await self.client.get(f"/project/{pack_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                console.print(f"[red]Modpack not found: {pack_id}[/red]")
            else:
                console.print(f"[red]Error fetching modpack {pack_id}: {e}[/red]")
            return None
        except Exception as e:
            console.print(f"[red]Error fetching modpack {pack_id}: {e}[/red]")
            return None
    
    async def get_modpack_versions(self, pack_id: str) -> List[Dict]:
        """Get versions for a modpack"""
        try:
            await self.rate_limiter.wait()
            response = await self.client.get(f"/project/{pack_id}/version")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error getting modpack versions: {e}[/red]")
            return []
        except Exception as e:
            console.print(f"[red]Error getting modpack versions: {e}[/red]")
            return []
    
    async def download_modpack_manifest(self, download_url: str) -> Optional[Dict]:
        """Download and parse modpack manifest"""
        try:
            await self.rate_limiter.wait()
            response = await self.client.get(download_url)
            response.raise_for_status()
            
            # Save to temporary file and extract
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                tmp.write(response.content)
                tmp_path = Path(tmp.name)
            
            try:
                with zipfile.ZipFile(tmp_path, 'r') as zip_file:
                    # Look for manifest file
                    manifest_files = ['modrinth.index.json', 'manifest.json']
                    for manifest_file in manifest_files:
                        if manifest_file in zip_file.namelist():
                            with zip_file.open(manifest_file) as f:
                                return json.load(f)
            finally:
                FileUtils.safe_remove(tmp_path)
            
            return None
        except Exception as e:
            console.print(f"[red]Error downloading modpack manifest: {e}[/red]")
            return None
    
    async def check_mod_updates(self, installed_mods: List[InstalledMod], 
                              minecraft_version: str, mod_loader: str) -> List[UpdateInfo]:
        """Check for updates to installed mods"""
        updates = []
        
        if not installed_mods:
            return updates
        
        # Get mod IDs that have version information
        mod_ids = [mod.mod_id for mod in installed_mods if mod.version_id]
        
        if not mod_ids:
            return updates
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True
        ) as progress:
            task = progress.add_task("Checking for updates...", total=len(mod_ids))
            
            for mod_id in mod_ids:
                progress.update(task, description=f"Checking {mod_id}...")
                
                try:
                    versions = await self.get_mod_versions(mod_id, minecraft_version, mod_loader)
                    if versions:
                        latest_version = versions[0]
                        installed_mod = next((m for m in installed_mods if m.mod_id == mod_id), None)
                        
                        if installed_mod and installed_mod.version_id != latest_version.get("id"):
                            files = latest_version.get("files", [])
                            if files:
                                primary_file = next((f for f in files if f.get("primary")), files[0])
                                updates.append(UpdateInfo(
                                    item_type="mod",
                                    item_id=mod_id,
                                    current_version=installed_mod.version,
                                    new_version=latest_version.get("version_number", "Unknown"),
                                    download_url=primary_file["url"],
                                    changelog=latest_version.get("changelog", "")
                                ))
                except Exception as e:
                    console.print(f"[dim]Warning: Could not check updates for {mod_id}: {e}[/dim]")
                
                progress.advance(task)
        
        return updates
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


class BatchModProcessor:
    """Handles batch mod operations"""
    
    def __init__(self, mod_manager: ModManager, api: ModrinthAPI):
        self.mod_manager = mod_manager
        self.api = api
    
    async def process_mod_list_file(self, file_path: Path) -> Tuple[List[ModInfo], List[str]]:
        """Process a text file containing mod names/IDs"""
        if not file_path.exists():
            console.print(f"[red]File not found: {file_path}[/red]")
            return [], []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            console.print(f"[red]Error reading file: {e}[/red]")
            return [], []
        
        mod_names = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):  # Skip empty lines and comments
                mod_names.append(line)
        
        if not mod_names:
            console.print(f"[yellow]No mod names found in {file_path}[/yellow]")
            return [], []
        
        console.print(f"[blue]Processing {len(mod_names)} mods from {file_path}[/blue]")
        return await self.process_mod_names(mod_names)
    
    async def process_mod_names(self, mod_names: List[str]) -> Tuple[List[ModInfo], List[str]]:
        """Process a list of mod names/IDs"""
        found_mods = []
        failed_mods = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        ) as progress:
            task = progress.add_task("Searching for mods...", total=len(mod_names))
            
            for mod_name in mod_names:
                progress.update(task, description=f"Searching for {mod_name}...")
                
                try:
                    # Try to get mod directly by ID first
                    mod_data = await self.api.get_mod_by_id(mod_name)
                    if mod_data:
                        mod_info = await self.create_mod_info_from_api_data(mod_data)
                        if mod_info:
                            found_mods.append(mod_info)
                        else:
                            failed_mods.append(mod_name)
                    else:
                        # Search by name
                        search_results = await self.api.search_mods(mod_name, limit=1)
                        if search_results:
                            mod_info = await self.create_mod_info_from_search_result(search_results[0])
                            if mod_info:
                                found_mods.append(mod_info)
                            else:
                                failed_mods.append(mod_name)
                        else:
                            failed_mods.append(mod_name)
                except Exception as e:
                    console.print(f"[dim]Warning: Error processing {mod_name}: {e}[/dim]")
                    failed_mods.append(mod_name)
                
                progress.advance(task)
        
        return found_mods, failed_mods
    
    async def create_mod_info_from_api_data(self, mod_data: Dict) -> Optional[ModInfo]:
        """Create ModInfo from API mod data"""
        try:
            # Get latest compatible version
            versions = await self.api.get_mod_versions(
                mod_data["id"],
                self.mod_manager.config["minecraft_version"],
                self.mod_manager.config["mod_loader"]
            )
            
            if not versions:
                return None
            
            latest_version = versions[0]
            if not latest_version.get("files"):
                return None
            
            # Get primary file
            files = latest_version["files"]
            primary_file = next((f for f in files if f.get("primary")), files[0])
            
            return ModInfo(
                id=mod_data["id"],
                name=mod_data["title"],
                description=mod_data.get("description", "No description"),
                author=mod_data.get("team", "Unknown"),
                downloads=mod_data.get("downloads", 0),
                categories=mod_data.get("categories", []),
                game_versions=latest_version.get("game_versions", []),
                download_url=primary_file["url"],
                filename=primary_file["filename"],
                mod_loader=self.mod_manager.config["mod_loader"],
                file_size=primary_file.get("size", 0),
                project_url=f"https://modrinth.com/mod/{mod_data['id']}",
                version_id=latest_version["id"],
                version_number=latest_version.get("version_number", ""),
                file_hash=primary_file.get("hashes", {}).get("sha256", ""),
                last_updated=latest_version.get("date_published", "")
            )
        except Exception as e:
            console.print(f"[red]Error creating mod info: {e}[/red]")
            return None
    
    async def create_mod_info_from_search_result(self, search_result: Dict) -> Optional[ModInfo]:
        """Create ModInfo from search result"""
        try:
            # Get mod details
            mod_data = await self.api.get_mod_by_id(search_result["project_id"])
            if not mod_data:
                return None
            
            return await self.create_mod_info_from_api_data(mod_data)
        except Exception as e:
            console.print(f"[red]Error creating mod info from search: {e}[/red]")
            return None
    
    async def process_modpack(self, pack_id: str) -> Tuple[List[ModInfo], Optional[str]]:
        """Process a modpack and extract mod list"""
        console.print(f"[blue]Processing modpack: {pack_id}[/blue]")
        
        # Get modpack details
        pack_data = await self.api.get_modpack_details(pack_id)
        if not pack_data:
            return [], "Could not fetch modpack details"
        
        # Get latest version
        versions = await self.api.get_modpack_versions(pack_id)
        if not versions:
            return [], "No versions found for modpack"
        
        latest_version = versions[0]
        if not latest_version.get("files"):
            return [], "No files found in modpack version"
        
        # Get primary file
        files = latest_version["files"]
        primary_file = next((f for f in files if f.get("primary")), files[0])
        
        # Download and parse manifest
        with Status("Downloading modpack manifest...", spinner="dots"):
            manifest = await self.api.download_modpack_manifest(primary_file["url"])
        
        if not manifest:
            return [], "Could not download or parse modpack manifest"
        
        # Extract mod list from manifest
        mod_ids = []
        if "files" in manifest:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
            ) as progress:
                task = progress.add_task("Extracting mod list...", total=len(manifest["files"]))
                
                for file_info in manifest["files"]:
                    progress.update(task, description=f"Processing file...")
                    
                    if "downloads" in file_info:
                        # Extract mod ID from download URL
                        for download_url in file_info["downloads"]:
                            if "modrinth.com" in download_url:
                                # Extract project ID from URL
                                parts = download_url.split("/")
                                if len(parts) >= 5:
                                    mod_ids.append(parts[4])
                                    break
                    
                    progress.advance(task)
        
        if not mod_ids:
            return [], "No mods found in modpack manifest"
        
        # Get mod details
        console.print(f"[blue]Found {len(mod_ids)} mods in modpack[/blue]")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        ) as progress:
            task = progress.add_task("Fetching mod details...", total=len(mod_ids))
            
            # Process mods in batches to avoid API limits
            batch_size = 10
            found_mods = []
            
            for i in range(0, len(mod_ids), batch_size):
                batch = mod_ids[i:i+batch_size]
                progress.update(task, description=f"Processing batch {i//batch_size + 1}...")
                
                mod_details = await self.api.get_mods_by_ids(batch)
                
                for mod_data in mod_details:
                    mod_info = await self.create_mod_info_from_api_data(mod_data)
                    if mod_info:
                        found_mods.append(mod_info)
                
                progress.advance(task, advance=len(batch))
        
        return found_mods, None


def format_mod_table(mods: List[Dict]) -> Table:
    """Format mods into a rich table"""
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Name", style="bold")
    table.add_column("Author", style="cyan")
    table.add_column("Downloads", justify="right", style="green")
    table.add_column("Description", style="dim", max_width=50)
    
    for i, mod in enumerate(mods):
        description = mod.get("description", "No description")
        if len(description) > 60:
            description = description[:60] + "..."
        
        table.add_row(
            str(i + 1),
            mod.get("title", "Unknown"),
            mod.get("author", "Unknown"),
            f"{mod.get('downloads', 0):,}",
            description
        )
    
    return table


def format_modpack_table(modpacks: List[Dict]) -> Table:
    """Format modpacks into a rich table"""
    table = Table(show_header=True, header_style="bold green")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Name", style="bold")
    table.add_column("Author", style="cyan")
    table.add_column("Downloads", justify="right", style="green")
    table.add_column("Description", style="dim", max_width=50)
    
    for i, pack in enumerate(modpacks):
        description = pack.get("description", "No description")
        if len(description) > 60:
            description = description[:60] + "..."
        
        table.add_row(
            str(i + 1),
            pack.get("title", "Unknown"),
            pack.get("author", "Unknown"),
            f"{pack.get('downloads', 0):,}",
            description
        )
    
    return table


def format_staged_mods_table(mods: List[ModInfo]) -> Table:
    """Format staged mods into a rich table"""
    table = Table(show_header=True, header_style="bold green")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Name", style="bold")
    table.add_column("Author", style="cyan")
    table.add_column("Version", style="yellow")
    table.add_column("Loader", style="magenta")
    table.add_column("Size", justify="right", style="blue")
    
    for i, mod in enumerate(mods):
        size_str = format_file_size(mod.file_size) if mod.file_size > 0 else "Unknown"
        
        table.add_row(
            str(i + 1),
            mod.name,
            mod.author,
            ", ".join(mod.game_versions[:2]) + ("..." if len(mod.game_versions) > 2 else ""),
            mod.mod_loader,
            size_str
        )
    
    return table


def format_installed_mods_table(mods: List[InstalledMod]) -> Table:
    """Format installed mods into a rich table"""
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Name", style="bold")
    table.add_column("Version", style="yellow")
    table.add_column("Author", style="cyan")
    table.add_column("Loader", style="green")
    table.add_column("Size", justify="right", style="blue")
    
    for i, mod in enumerate(mods):
        size_str = format_file_size(mod.file_size)
        
        table.add_row(
            str(i + 1),
            mod.name,
            mod.version,
            mod.author,
            mod.mod_loader,
            size_str
        )
    
    return table


def format_loader_versions_table(loaders: List[ModLoaderInfo]) -> Table:
    """Format loader versions into a rich table"""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Loader", style="bold")
    table.add_column("Version", style="yellow")
    table.add_column("MC Version", style="green")
    table.add_column("Stability", style="magenta")
    
    for i, loader in enumerate(loaders):
        stability = "✓ Stable" if loader.stable else "⚠ Beta"
        table.add_row(
            str(i + 1),
            loader.loader_type.title(),
            loader.loader_version,
            loader.minecraft_version,
            stability
        )
    
    return table


def format_installed_loaders_table(loaders: List[InstalledLoader]) -> Table:
    """Format installed loaders into a rich table"""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Loader", style="bold")
    table.add_column("MC Version", style="green")
    table.add_column("Profile", style="yellow")
    table.add_column("Installed", style="dim")
    
    for i, loader in enumerate(loaders):
        install_date = ""
        if loader.install_date:
            try:
                dt = datetime.fromisoformat(loader.install_date)
                install_date = dt.strftime("%Y-%m-%d")
            except ValueError:
                install_date = "Unknown"
        
        table.add_row(
            str(i + 1),
            loader.loader_type.title(),
            loader.minecraft_version,
            loader.profile_name,
            install_date
        )
    
    return table


def format_updates_table(updates: List[UpdateInfo]) -> Table:
    """Format updates into a rich table"""
    table = Table(show_header=True, header_style="bold yellow")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Type", style="bold")
    table.add_column("Item", style="cyan")
    table.add_column("Current", style="red")
    table.add_column("New", style="green")
    
    for i, update in enumerate(updates):
        table.add_row(
            str(i + 1),
            update.item_type.title(),
            update.item_id,
            update.current_version,
            update.new_version
        )
    
    return table


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """🎮 Minecraft Mod Manager - Search, stage, and install mods and loaders!"""
    pass


# Mod commands
@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=10, help="Maximum number of results")
def search(query: str, limit: int):
    """Search for Minecraft mods"""
    asyncio.run(search_async(query, limit))


async def search_async(query: str, limit: int):
    """Async search implementation"""
    console.print(f"[bold blue]Searching for mods: {query}[/bold blue]")
    
    api = ModrinthAPI()
    
    try:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Searching...", total=None)
            results = await api.search_mods(query, limit)
        
        if not results:
            console.print("[red]No mods found![/red]")
            console.print("[dim]Try adjusting your search terms or check your internet connection.[/dim]")
            return
        
        console.print(f"\n[bold green]Found {len(results)} mods:[/bold green]")
        table = format_mod_table(results)
        console.print(table)
        
        # Interactive selection
        if Confirm.ask("\nWould you like to add any of these mods to staging?"):
            mod_manager = ModManager()
            
            while True:
                try:
                    choice = Prompt.ask(
                        "Enter mod number to add (or 'done' to finish)",
                        default="done"
                    )
                    
                    if choice.lower() == "done":
                        break
                    
                    mod_index = int(choice) - 1
                    if 0 <= mod_index < len(results):
                        await add_mod_to_staging(results[mod_index], mod_manager, api)
                    else:
                        console.print("[red]Invalid mod number![/red]")
                        
                except ValueError:
                    console.print("[red]Please enter a valid number or 'done'[/red]")
                except KeyboardInterrupt:
                    console.print("\n[yellow]Operation cancelled[/yellow]")
                    break
    
    except Exception as e:
        console.print(f"[red]Error during search: {e}[/red]")
    
    finally:
        await api.close()


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
def batch(file_path: str):
    """Add mods from a text file to staging"""
    asyncio.run(batch_async(Path(file_path)))


async def batch_async(file_path: Path):
    """Async batch processing"""
    console.print(f"[bold blue]Processing batch file: {file_path}[/bold blue]")
    
    mod_manager = ModManager()
    api = ModrinthAPI()
    processor = BatchModProcessor(mod_manager, api)
    
    try:
        found_mods, failed_mods = await processor.process_mod_list_file(file_path)
        
        if found_mods:
            console.print(f"\n[bold green]Found {len(found_mods)} mods:[/bold green]")
            
            # Show what was found
            for i, mod in enumerate(found_mods[:10]):  # Show first 10
                console.print(f"  {i+1}. {mod.name} by {mod.author}")
            
            if len(found_mods) > 10:
                console.print(f"  ... and {len(found_mods) - 10} more")
            
            if Confirm.ask(f"\nAdd {len(found_mods)} mods to staging?"):
                added_count, skipped_count = mod_manager.add_mods_to_staging(found_mods)
                console.print(f"[green]✓[/green] Added {added_count} mods to staging")
                if skipped_count > 0:
                    console.print(f"[yellow]⚠[/yellow] Skipped {skipped_count} mods (already staged)")
        
        if failed_mods:
            console.print(f"\n[bold red]Failed to find {len(failed_mods)} mods:[/bold red]")
            for mod_name in failed_mods:
                console.print(f"  - {mod_name}")
    
    except Exception as e:
        console.print(f"[red]Error processing batch file: {e}[/red]")
    
    finally:
        await api.close()


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=10, help="Maximum number of results")
def modpack(query: str, limit: int):
    """Search for and install modpacks"""
    asyncio.run(modpack_async(query, limit))


async def modpack_async(query: str, limit: int):
    """Async modpack search and installation"""
    console.print(f"[bold blue]Searching for modpacks: {query}[/bold blue]")
    
    api = ModrinthAPI()
    
    try:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Searching...", total=None)
            results = await api.search_modpacks(query, limit)
        
        if not results:
            console.print("[red]No modpacks found![/red]")
            console.print("[dim]Try adjusting your search terms or check your internet connection.[/dim]")
            return
        
        console.print(f"\n[bold green]Found {len(results)} modpacks:[/bold green]")
        table = format_modpack_table(results)
        console.print(table)
        
        # Interactive selection
        if Confirm.ask("\nWould you like to install any of these modpacks?"):
            try:
                choice = Prompt.ask(
                    "Enter modpack number to install",
                    default="1"
                )
                
                pack_index = int(choice) - 1
                if 0 <= pack_index < len(results):
                    selected_pack = results[pack_index]
                    await install_modpack(selected_pack, api)
                else:
                    console.print("[red]Invalid modpack number![/red]")
                    
            except ValueError:
                console.print("[red]Please enter a valid number[/red]")
            except KeyboardInterrupt:
                console.print("\n[yellow]Operation cancelled[/yellow]")
    
    except Exception as e:
        console.print(f"[red]Error during modpack search: {e}[/red]")
    
    finally:
        await api.close()


async def install_modpack(pack_data: Dict, api: ModrinthAPI):
    """Install a modpack"""
    console.print(f"[bold blue]Installing modpack: {pack_data['title']}[/bold blue]")
    
    mod_manager = ModManager()
    processor = BatchModProcessor(mod_manager, api)
    
    try:
        found_mods, error = await processor.process_modpack(pack_data["project_id"])
        
        if error:
            console.print(f"[red]Error: {error}[/red]")
            return
        
        if not found_mods:
            console.print("[red]No mods found in modpack![/red]")
            return
        
        console.print(f"\n[bold green]Found {len(found_mods)} mods in modpack:[/bold green]")
        
        # Show first few mods
        for i, mod in enumerate(found_mods[:5]):
            console.print(f"  {i+1}. {mod.name} by {mod.author}")
        
        if len(found_mods) > 5:
            console.print(f"  ... and {len(found_mods) - 5} more")
        
        if Confirm.ask(f"\nAdd all {len(found_mods)} mods to staging?"):
            added_count, skipped_count = mod_manager.add_mods_to_staging(found_mods)
            console.print(f"[green]✓[/green] Added {added_count} mods to staging")
            if skipped_count > 0:
                console.print(f"[yellow]⚠[/yellow] Skipped {skipped_count} mods (already staged)")
            
            if added_count > 0 and Confirm.ask("Install all staged mods now?"):
                await install_staged_mods(mod_manager)
    
    except Exception as e:
        console.print(f"[red]Error installing modpack: {e}[/red]")


async def add_mod_to_staging(mod_data: Dict, mod_manager: ModManager, api: ModrinthAPI):
    """Add a mod to staging with version selection"""
    console.print(f"[bold]Getting versions for {mod_data['title']}...[/bold]")
    
    versions = await api.get_mod_versions(
        mod_data["project_id"],
        mod_manager.config["minecraft_version"],
        mod_manager.config["mod_loader"]
    )
    
    if not versions:
        console.print(f"[red]No compatible versions found for {mod_data['title']}![/red]")
        console.print(f"[dim]Looking for: MC {mod_manager.config['minecraft_version']}, {mod_manager.config['mod_loader']}[/dim]")
        return
    
    # Use the latest version
    latest_version = versions[0]
    if not latest_version.get("files"):
        console.print(f"[red]No files available for {mod_data['title']}![/red]")
        return
    
    # Get primary file
    files = latest_version["files"]
    primary_file = next((f for f in files if f.get("primary")), files[0])
    
    mod_info = ModInfo(
        id=mod_data["project_id"],
        name=mod_data["title"],
        description=mod_data.get("description", "No description"),
        author=mod_data.get("author", "Unknown"),
        downloads=mod_data.get("downloads", 0),
        categories=mod_data.get("categories", []),
        game_versions=latest_version.get("game_versions", []),
        download_url=primary_file["url"],
        filename=primary_file["filename"],
        mod_loader=mod_manager.config["mod_loader"],
        file_size=primary_file.get("size", 0),
        project_url=f"https://modrinth.com/mod/{mod_data['project_id']}",
        version_id=latest_version["id"],
        version_number=latest_version.get("version_number", ""),
        file_hash=primary_file.get("hashes", {}).get("sha256", ""),
        last_updated=latest_version.get("date_published", "")
    )
    
    mod_manager.add_to_staging(mod_info)


@cli.command()
def list():
    """List all staged mods"""
    mod_manager = ModManager()
    staged_mods = mod_manager.get_staged_mods()
    
    if not staged_mods:
        console.print("[yellow]No mods in staging area[/yellow]")
        console.print("[dim]Use 'mcmod search' or 'mcmod batch' to add mods[/dim]")
        return
    
    console.print(f"[bold green]Staged mods ({len(staged_mods)}):[/bold green]")
    table = format_staged_mods_table(staged_mods)
    console.print(table)
    
    # Show total size
    total_size = sum(mod.file_size for mod in staged_mods if mod.file_size > 0)
    if total_size > 0:
        console.print(f"\n[bold]Total download size: {format_file_size(total_size)}[/bold]")


@cli.command()
def installed():
    """List all installed mods"""
    mod_manager = ModManager()
    
    # Get mod directory as string
    mod_directory = mod_manager.config["mod_directory"]
    if isinstance(mod_directory, Path):
        mod_directory = str(mod_directory)
    
    mod_dir = Path(mod_directory)
    
    if not mod_dir.exists():
        console.print(f"[red]Mod directory {mod_dir} does not exist![/red]")
        console.print(f"[dim]You can set a different directory with: mcmod config[/dim]")
        if Confirm.ask("Create the mod directory?"):
            if FileUtils.safe_create_dir(mod_dir):
                console.print(f"[green]✓[/green] Created mod directory: {mod_dir}")
            else:
                return
        else:
            return
    
    try:
        installed_mods = mod_manager.get_installed_mods()
    except Exception as e:
        console.print(f"[red]Error scanning mods: {e}[/red]")
        return
    
    if not installed_mods:
        console.print("[yellow]No mods installed[/yellow]")
        console.print(f"[dim]Install mods with: mcmod install[/dim]")
        return
    
    console.print(f"[bold magenta]Installed mods ({len(installed_mods)}):[/bold magenta]")
    console.print(f"[dim]Location: {mod_dir}[/dim]\n")
    
    table = format_installed_mods_table(installed_mods)
    console.print(table)
    
    # Show summary
    total_size = sum(mod.file_size for mod in installed_mods)
    console.print(f"\n[bold]Total: {len(installed_mods)} mods, {format_file_size(total_size)}[/bold]")


@cli.command()
@click.argument("mod_number", type=int)
def remove(mod_number: int):
    """Remove a mod from staging by number"""
    mod_manager = ModManager()
    staged_mods = mod_manager.get_staged_mods()
    
    if not staged_mods:
        console.print("[yellow]No mods in staging area[/yellow]")
        return
    
    if 1 <= mod_number <= len(staged_mods):
        mod_to_remove = staged_mods[mod_number - 1]
        if Confirm.ask(f"Remove '{mod_to_remove.name}' from staging?"):
            mod_manager.remove_from_staging(mod_to_remove.id)
    else:
        console.print("[red]Invalid mod number![/red]")


@cli.command()
@click.argument("mod_number", type=int)
def uninstall(mod_number: int):
    """Uninstall a mod by number"""
    mod_manager = ModManager()
    installed_mods = mod_manager.get_installed_mods()
    
    if not installed_mods:
        console.print("[yellow]No mods installed[/yellow]")
        return
    
    if 1 <= mod_number <= len(installed_mods):
        mod_to_remove = installed_mods[mod_number - 1]
        
        if Confirm.ask(f"Are you sure you want to uninstall '{mod_to_remove.name}'?"):
            if mod_manager.remove_installed_mod(mod_to_remove.filename):
                console.print(f"[green]✓[/green] Uninstalled {mod_to_remove.name}")
            else:
                console.print(f"[red]✗[/red] Failed to uninstall {mod_to_remove.name}")
    else:
        console.print("[red]Invalid mod number![/red]")


@cli.command()
def clear():
    """Clear all staged mods"""
    mod_manager = ModManager()
    staged_mods = mod_manager.get_staged_mods()
    
    if not staged_mods:
        console.print("[yellow]No mods in staging area[/yellow]")
        return
    
    if Confirm.ask(f"Are you sure you want to clear {len(staged_mods)} staged mods?"):
        mod_manager.clear_staging()


@cli.command()
def clean():
    """Clean all mods from the mods folder"""
    mod_manager = ModManager()
    mod_dir = Path(mod_manager.config["mod_directory"])
    
    if not mod_dir.exists():
        console.print(f"[red]Mod directory {mod_dir} does not exist![/red]")
        return
    
    # Get count of mods to delete
    try:
        mod_files = list(mod_dir.glob("*.jar"))
    except Exception as e:
        console.print(f"[red]Error accessing mod directory: {e}[/red]")
        return
    
    if not mod_files:
        console.print("[yellow]No mods to clean[/yellow]")
        return
    
    console.print(f"[bold red]This will delete {len(mod_files)} mod files from {mod_dir}[/bold red]")
    if mod_manager.config.get("backup_enabled", True):
        console.print("[blue]Backups will be created before deletion[/blue]")
    
    if Confirm.ask("Are you sure you want to delete ALL mods?"):
        removed_count = mod_manager.clean_mods_folder()
        console.print(f"[green]✓[/green] Cleaned {removed_count} mods from mods folder")


@cli.command()
def install():
    """Download and install all staged mods"""
    asyncio.run(install_async())


async def install_async():
    """Async install implementation"""
    mod_manager = ModManager()
    await install_staged_mods(mod_manager)


async def install_staged_mods(mod_manager: ModManager):
    """Install all staged mods"""
    staged_mods = mod_manager.get_staged_mods()
    
    if not staged_mods:
        console.print("[yellow]No mods in staging area[/yellow]")
        return
    
    if not mod_manager.ensure_mod_directory_exists():
        console.print("[red]Installation cancelled - cannot access mod directory[/red]")
        return
    
    mod_dir = Path(mod_manager.config["mod_directory"])
    console.print(f"[bold green]Installing {len(staged_mods)} mods to {mod_dir}[/bold green]")
    
    # Calculate total download size
    total_size = sum(mod.file_size for mod in staged_mods if mod.file_size > 0)
    if total_size > 0:
        console.print(f"[blue]Total download size: {format_file_size(total_size)}[/blue]")
    
    rate_limiter = RateLimiter()
    
    async with httpx.AsyncClient() as client:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            DownloadColumn(),
        ) as progress:
            main_task = progress.add_task("Installing mods...", total=len(staged_mods))
            
            successful_installs = 0
            failed_installs = 0
            
            for mod in staged_mods:
                progress.update(main_task, description=f"Downloading {mod.name}...")
                
                try:
                    # Rate limiting
                    await rate_limiter.wait()
                    
                    # Download mod file
                    response = await client.get(mod.download_url)
                    response.raise_for_status()
                    
                    # Save to mod directory
                    mod_path = mod_dir / mod.filename
                    with open(mod_path, 'wb') as f:
                        f.write(response.content)
                    
                    # Verify file hash if available
                    if mod.file_hash:
                        calculated_hash = FileUtils.calculate_file_hash(mod_path)
                        if calculated_hash and calculated_hash != mod.file_hash:
                            console.print(f"[yellow]⚠[/yellow] Hash mismatch for {mod.name} (continuing anyway)")
                    
                    console.print(f"[green]✓[/green] Installed {mod.name}")
                    successful_installs += 1
                    
                except httpx.HTTPStatusError as e:
                    console.print(f"[red]✗[/red] Failed to download {mod.name}: HTTP {e.response.status_code}")
                    failed_installs += 1
                except Exception as e:
                    console.print(f"[red]✗[/red] Failed to install {mod.name}: {e}")
                    failed_installs += 1
                
                progress.advance(main_task)
    
    # Summary
    console.print(f"\n[bold green]Installation complete![/bold green]")
    console.print(f"[green]✓[/green] Successfully installed: {successful_installs}")
    if failed_installs > 0:
        console.print(f"[red]✗[/red] Failed to install: {failed_installs}")
    
    if successful_installs > 0:
        # Update installed mods record
        mod_manager.get_installed_mods()  # This will rescan and update the record
        
        if Confirm.ask("Clear staging area?"):
            mod_manager.clear_staging()


@cli.command()
def update():
    """Check for updates to installed mods"""
    asyncio.run(update_async())


async def update_async():
    """Check for updates to installed mods"""
    mod_manager = ModManager()
    api = ModrinthAPI()
    
    try:
        console.print("[bold blue]Checking for mod updates...[/bold blue]")
        
        installed_mods = mod_manager.get_installed_mods()
        if not installed_mods:
            console.print("[yellow]No installed mods found[/yellow]")
            return
        
        updates = await api.check_mod_updates(
            installed_mods,
            mod_manager.config["minecraft_version"],
            mod_manager.config["mod_loader"]
        )
        
        if not updates:
            console.print("[green]✓[/green] All mods are up to date!")
            return
        
        console.print(f"\n[bold yellow]Found {len(updates)} updates available:[/bold yellow]")
        table = format_updates_table(updates)
        console.print(table)
        
        if Confirm.ask("\nWould you like to update these mods?"):
            # Add updated versions to staging
            for update in updates:
                # Create ModInfo from update
                mod_info = ModInfo(
                    id=update.item_id,
                    name=update.item_id,  # We'll get the proper name when we fetch details
                    description="",
                    author="",
                    downloads=0,
                    categories=[],
                    game_versions=[],
                    download_url=update.download_url,
                    filename="",  # Will be set when we get the file info
                    mod_loader=mod_manager.config["mod_loader"],
                    version_number=update.new_version
                )
                
                # TODO: Implement proper mod update staging
                console.print(f"[blue]Update for {update.item_id} would be staged here[/blue]")
        
    except Exception as e:
        console.print(f"[red]Error checking for updates: {e}[/red]")
    
    finally:
        await api.close()


# Loader commands
@cli.command()
def loaders():
    """List installed mod loaders"""
    loader_manager = ModLoaderManager()
    installed_loaders = loader_manager.detect_installed_loaders()
    
    if not installed_loaders:
        console.print("[yellow]No mod loaders detected[/yellow]")
        console.print("[dim]Try running 'mcmod loader install' to install a loader[/dim]")
        return
    
    console.print(f"[bold cyan]Installed mod loaders ({len(installed_loaders)}):[/bold cyan]")
    table = format_installed_loaders_table(installed_loaders)
    console.print(table)


@cli.group()
def loader():
    """Manage mod loaders (Fabric, Forge, Quilt)"""
    pass


@loader.command()
@click.option("--loader", "-l", type=click.Choice(["fabric", "forge", "quilt"]), help="Specific loader type")
@click.option("--mc-version", "-v", help="Minecraft version")
def install(loader: str, mc_version: str):
    """Install a mod loader"""
    asyncio.run(install_loader_async(loader, mc_version))


async def install_loader_async(loader_type: str, mc_version: str):
    """Async loader installation"""
    loader_manager = ModLoaderManager()
    mod_manager = ModManager()
    
    try:
        # Use config version if not specified
        if not mc_version:
            mc_version = mod_manager.config["minecraft_version"]
        
        # Get available loaders
        if not loader_type:
            loader_type = Prompt.ask(
                "Select loader type",
                choices=["fabric", "forge", "quilt"],
                default="fabric"
            )
        
        console.print(f"[bold blue]Getting {loader_type} versions for Minecraft {mc_version}...[/bold blue]")
        
        # Get available versions
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Fetching versions...", total=None)
            
            if loader_type == "fabric":
                versions = await loader_manager.get_fabric_versions(mc_version)
            elif loader_type == "forge":
                versions = await loader_manager.get_forge_versions(mc_version)
            elif loader_type == "quilt":
                versions = await loader_manager.get_quilt_versions(mc_version)
        
        if not versions:
            console.print(f"[red]No {loader_type} versions found for Minecraft {mc_version}[/red]")
            return
        
        # Display available versions
        console.print(f"\n[bold green]Available {loader_type} versions:[/bold green]")
        table = format_loader_versions_table(versions)
        console.print(table)
        
        # Let user select version
        try:
            choice = Prompt.ask(
                "Select version number to install",
                default="1"
            )
            
            version_index = int(choice) - 1
            if 0 <= version_index < len(versions):
                selected_version = versions[version_index]
                
                minecraft_dir = loader_manager.get_minecraft_dir()
                console.print(f"[dim]Installing to: {minecraft_dir}[/dim]")
                
                if Confirm.ask(f"Install {selected_version.loader_type} {selected_version.loader_version} for MC {selected_version.minecraft_version}?"):
                    success = await loader_manager.install_loader(selected_version, minecraft_dir)
                    if success:
                        console.print(f"[green]✓[/green] Successfully installed {selected_version.loader_type} {selected_version.loader_version}")
                    else:
                        console.print(f"[red]✗[/red] Failed to install {selected_version.loader_type}")
            else:
                console.print("[red]Invalid version number![/red]")
                
        except ValueError:
            console.print("[red]Please enter a valid number[/red]")
        except KeyboardInterrupt:
            console.print("\n[yellow]Installation cancelled[/yellow]")
    
    except Exception as e:
        console.print(f"[red]Error during loader installation: {e}[/red]")
    
    finally:
        await loader_manager.close()


@loader.command()
@click.option("--loader", "-l", type=click.Choice(["fabric", "forge", "quilt"]), help="Specific loader type")
@click.option("--mc-version", "-v", help="Minecraft version")
def versions(loader: str, mc_version: str):
    """List available mod loader versions"""
    asyncio.run(list_loader_versions_async(loader, mc_version))


async def list_loader_versions_async(loader_type: str, mc_version: str):
    """Async loader version listing"""
    loader_manager = ModLoaderManager()
    mod_manager = ModManager()
    
    try:
        # Use config version if not specified
        if not mc_version:
            mc_version = mod_manager.config["minecraft_version"]
        
        # Get available loaders
        if not loader_type:
            loader_type = Prompt.ask(
                "Select loader type",
                choices=["fabric", "forge", "quilt"],
                default="fabric"
            )
        
        console.print(f"[bold blue]Getting {loader_type} versions for Minecraft {mc_version}...[/bold blue]")
        
        # Get available versions
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Fetching versions...", total=None)
            
            if loader_type == "fabric":
                versions = await loader_manager.get_fabric_versions(mc_version)
            elif loader_type == "forge":
                versions = await loader_manager.get_forge_versions(mc_version)
            elif loader_type == "quilt":
                versions = await loader_manager.get_quilt_versions(mc_version)
        
        if not versions:
            console.print(f"[red]No {loader_type} versions found for Minecraft {mc_version}[/red]")
            return
        
        # Display available versions
        console.print(f"\n[bold green]Available {loader_type} versions for MC {mc_version}:[/bold green]")
        table = format_loader_versions_table(versions)
        console.print(table)
    
    except Exception as e:
        console.print(f"[red]Error fetching loader versions: {e}[/red]")
    
    finally:
        await loader_manager.close()


@loader.command()
@click.argument("loader_number", type=int)
def uninstall(loader_number: int):
    """Uninstall a mod loader by number"""
    loader_manager = ModLoaderManager()
    installed_loaders = loader_manager.detect_installed_loaders()
    
    if not installed_loaders:
        console.print("[yellow]No mod loaders installed[/yellow]")
        return
    
    if 1 <= loader_number <= len(installed_loaders):
        loader_to_remove = installed_loaders[loader_number - 1]
        
        console.print(f"[bold red]This will uninstall {loader_to_remove.loader_type} profile: {loader_to_remove.profile_name}[/bold red]")
        if Confirm.ask("Are you sure you want to uninstall this loader?"):
            if loader_manager.uninstall_loader(loader_to_remove):
                console.print(f"[green]✓[/green] Successfully uninstalled {loader_to_remove.loader_type}")
            else:
                console.print(f"[red]✗[/red] Failed to uninstall {loader_to_remove.loader_type}")
    else:
        console.print("[red]Invalid loader number![/red]")


@loader.command()
def clean():
    """Clean all mod loader installations"""
    loader_manager = ModLoaderManager()
    minecraft_dir = loader_manager.get_minecraft_dir()
    
    console.print(f"[bold red]This will remove ALL mod loader profiles from {minecraft_dir}[/bold red]")
    console.print("[yellow]This action cannot be undone![/yellow]")
    
    if Confirm.ask("Are you sure you want to clean all mod loaders?"):
        removed_count = loader_manager.clean_all_loaders(minecraft_dir)
        console.print(f"[green]✓[/green] Cleaned {removed_count} mod loader profiles")


@loader.command()
def update():
    """Check for updates to installed loaders"""
    console.print("[yellow]Loader update functionality coming soon![/yellow]")
    console.print("[dim]This will check for updates to your installed mod loaders[/dim]")


@cli.command()
def config():
    """Configure mod manager settings"""
    mod_manager = ModManager()
    
    console.print("[bold blue]Current Configuration:[/bold blue]")
    for key, value in mod_manager.config.items():
        console.print(f"  {key}: [yellow]{value}[/yellow]")
    
    console.print("\n[bold]Update settings:[/bold]")
    
    # Update mod directory
    new_mod_dir = Prompt.ask(
        "Mod directory",
        default=mod_manager.config["mod_directory"]
    )
    mod_manager.config["mod_directory"] = new_mod_dir
    
    # Update Minecraft version
    new_mc_version = Prompt.ask(
        "Minecraft version",
        default=mod_manager.config["minecraft_version"]
    )
    mod_manager.config["minecraft_version"] = new_mc_version
    
    # Update mod loader
    new_mod_loader = Prompt.ask(
        "Mod loader",
        default=mod_manager.config["mod_loader"],
        choices=["fabric", "forge", "quilt"]
    )
    mod_manager.config["mod_loader"] = new_mod_loader
    
    # Update backup setting
    backup_enabled = Confirm.ask(
        "Enable backups before mod operations?",
        default=mod_manager.config.get("backup_enabled", True)
    )
    mod_manager.config["backup_enabled"] = backup_enabled
    
    # Update auto-update check
    auto_update = Confirm.ask(
        "Enable automatic update checking?",
        default=mod_manager.config.get("auto_update_check", True)
    )
    mod_manager.config["auto_update_check"] = auto_update
    
    mod_manager.save_config()
    console.print("[green]✓[/green] Configuration updated!")


@cli.command()
def reset():
    """Reset all configuration and clear all data"""
    console.print("[bold red]This will reset ALL configuration and clear ALL data![/bold red]")
    console.print("[yellow]This includes:[/yellow]")
    console.print("  - Configuration settings")
    console.print("  - Staged mods")
    console.print("  - Installed mods record")
    console.print("  - Cache files")
    console.print("\n[dim]Your actual mod files will NOT be deleted[/dim]")
    
    if Confirm.ask("Are you sure you want to reset everything?"):
        try:
            # Remove all config files
            config_files = [
                STAGING_FILE,
                CONFIG_FILE,
                LOADER_CACHE_FILE,
                INSTALLED_MODS_FILE,
                MODPACK_HISTORY_FILE
            ]
            
            for config_file in config_files:
                FileUtils.safe_remove(config_file)
            
            console.print("[green]✓[/green] All configuration and data has been reset")
            console.print("[dim]Run 'mcmod config' to set up your preferences again[/dim]")
        except Exception as e:
            console.print(f"[red]Error during reset: {e}[/red]")


def main():
    """Main entry point"""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled[/yellow]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        console.print("[dim]Please report this issue if it persists[/dim]")


if __name__ == "__main__":
    main()
