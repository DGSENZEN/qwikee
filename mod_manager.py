#!/usr/bin/env python3
"""
Minecraft Mod Manager CLI
A tool to search, stage, and install Minecraft mods
"""

import os
import json
import shutil
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

import click
import httpx
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text

console = Console()

# Configuration
CONFIG_DIR = Path.home() / ".minecraft-mod-manager"
STAGING_FILE = CONFIG_DIR / "staging.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
MODRINTH_API_BASE = "https://api.modrinth.com/v2"


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

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "ModInfo":
        return cls(**data)


class ModManager:
    """Handles mod operations and staging"""
    
    def __init__(self):
        self.config_dir = CONFIG_DIR
        self.staging_file = STAGING_FILE
        self.config_file = CONFIG_FILE
        self.ensure_config_dir()
        self.load_config()
    
    def ensure_config_dir(self):
        """Create config directory if it doesn't exist"""
        self.config_dir.mkdir(exist_ok=True)
    
    def load_config(self):
        """Load configuration from file"""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        else:
            # Default config
            self.config = {
                "mod_directory": str(Path.home() / ".minecraft" / "mods"),
                "minecraft_version": "1.20.1",
                "mod_loader": "fabric"
            }
            self.save_config()
    
    def save_config(self):
        """Save configuration to file"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def get_staged_mods(self) -> List[ModInfo]:
        """Get list of staged mods"""
        if not self.staging_file.exists():
            return []
        
        with open(self.staging_file, 'r') as f:
            data = json.load(f)
            return [ModInfo.from_dict(mod) for mod in data]
    
    def save_staged_mods(self, mods: List[ModInfo]):
        """Save staged mods to file"""
        with open(self.staging_file, 'w') as f:
            json.dump([mod.to_dict() for mod in mods], f, indent=2)
    
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


class ModrinthAPI:
    """Handles Modrinth API interactions"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=MODRINTH_API_BASE,
            timeout=30.0
        )
    
    async def search_mods(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for mods on Modrinth"""
        params = {
            "query": query,
            "limit": limit,
            "facets": '["project_type:mod"]'
        }
        
        try:
            response = await self.client.get("/search", params=params)
            response.raise_for_status()
            return response.json()["hits"]
        except httpx.HTTPError as e:
            console.print(f"[red]Error searching mods: {e}[/red]")
            return []
    
    async def get_mod_versions(self, mod_id: str, minecraft_version: str, 
                             mod_loader: str) -> List[Dict]:
        """Get versions for a specific mod"""
        params = {
            "game_versions": f'["{minecraft_version}"]',
            "loaders": f'["{mod_loader}"]'
        }
        
        try:
            response = await self.client.get(f"/project/{mod_id}/version", 
                                           params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            console.print(f"[red]Error getting mod versions: {e}[/red]")
            return []
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


def format_mod_table(mods: List[Dict]) -> Table:
    """Format mods into a rich table"""
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Name", style="bold")
    table.add_column("Author", style="cyan")
    table.add_column("Downloads", justify="right", style="green")
    table.add_column("Description", style="dim", max_width=40)
    
    for i, mod in enumerate(mods):
        table.add_row(
            str(i + 1),
            mod["title"],
            mod["author"],
            f"{mod['downloads']:,}",
            mod["description"][:60] + "..." if len(mod["description"]) > 60 
            else mod["description"]
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
    
    for i, mod in enumerate(mods):
        table.add_row(
            str(i + 1),
            mod.name,
            mod.author,
            ", ".join(mod.game_versions[:2]) + ("..." if len(mod.game_versions) > 2 else ""),
            mod.mod_loader
        )
    
    return table


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """🎮 Minecraft Mod Manager - Search, stage, and install mods easily!"""
    pass


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=10, help="Maximum number of results")
async def search(query: str, limit: int):
    """Search for Minecraft mods"""
    console.print(f"[bold blue]Searching for mods: {query}[/bold blue]")
    
    api = ModrinthAPI()
    
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Searching...", total=None)
        results = await api.search_mods(query, limit)
    
    await api.close()
    
    if not results:
        console.print("[red]No mods found![/red]")
        return
    
    console.print(f"\n[bold green]Found {len(results)} mods:[/bold green]")
    table = format_mod_table(results)
    console.print(table)
    
    # Interactive selection
    if Confirm.ask("\nWould you like to add any of these mods to staging?"):
        mod_manager = ModManager()
        api = ModrinthAPI()
        
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
        
        await api.close()


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
        return
    
    # Use the latest version
    latest_version = versions[0]
    if not latest_version["files"]:
        console.print(f"[red]No files available for {mod_data['title']}![/red]")
        return
    
    # Get primary file
    primary_file = next(
        (f for f in latest_version["files"] if f["primary"]), 
        latest_version["files"][0]
    )
    
    mod_info = ModInfo(
        id=mod_data["project_id"],
        name=mod_data["title"],
        description=mod_data["description"],
        author=mod_data["author"],
        downloads=mod_data["downloads"],
        categories=mod_data["categories"],
        game_versions=latest_version["game_versions"],
        download_url=primary_file["url"],
        filename=primary_file["filename"],
        mod_loader=mod_manager.config["mod_loader"]
    )
    
    mod_manager.add_to_staging(mod_info)


@cli.command()
def list():
    """List all staged mods"""
    mod_manager = ModManager()
    staged_mods = mod_manager.get_staged_mods()
    
    if not staged_mods:
        console.print("[yellow]No mods in staging area[/yellow]")
        return
    
    console.print(f"[bold green]Staged mods ({len(staged_mods)}):[/bold green]")
    table = format_staged_mods_table(staged_mods)
    console.print(table)


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
        mod_manager.remove_from_staging(mod_to_remove.id)
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
async def install():
    """Download and install all staged mods"""
    mod_manager = ModManager()
    staged_mods = mod_manager.get_staged_mods()
    
    if not staged_mods:
        console.print("[yellow]No mods in staging area[/yellow]")
        return
    
    mod_dir = Path(mod_manager.config["mod_directory"])
    if not mod_dir.exists():
        if Confirm.ask(f"Mod directory {mod_dir} doesn't exist. Create it?"):
            mod_dir.mkdir(parents=True)
        else:
            console.print("[red]Installation cancelled[/red]")
            return
    
    console.print(f"[bold green]Installing {len(staged_mods)} mods to {mod_dir}[/bold green]")
    
    async with httpx.AsyncClient() as client:
        with Progress() as progress:
            task = progress.add_task("Installing mods...", total=len(staged_mods))
            
            for mod in staged_mods:
                progress.update(task, description=f"Downloading {mod.name}...")
                
                try:
                    # Download mod file
                    response = await client.get(mod.download_url)
                    response.raise_for_status()
                    
                    # Save to mod directory
                    mod_path = mod_dir / mod.filename
                    with open(mod_path, 'wb') as f:
                        f.write(response.content)
                    
                    console.print(f"[green]✓[/green] Installed {mod.name}")
                    
                except Exception as e:
                    console.print(f"[red]✗[/red] Failed to install {mod.name}: {e}")
                
                progress.advance(task)
    
    console.print(f"\n[bold green]Installation complete![/bold green]")
    
    if Confirm.ask("Clear staging area?"):
        mod_manager.clear_staging()


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
    
    mod_manager.save_config()
    console.print("[green]✓[/green] Configuration updated!")


def main():
    """Main entry point"""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled[/yellow]")


if __name__ == "__main__":
    main()
