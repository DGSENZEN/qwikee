## 🚀 Qwikee - Quick Minecraft Mod Installer

A lightning-fast, professional-grade tool for downloading and installing Minecraft mods from CurseForge and direct URLs. Get your mods installed in seconds, not minutes!

## ✨ Features

- ⚡ **Lightning Fast**: Resume interrupted downloads, parallel processing
- 🎯 **Smart Detection**: Automatically finds Minecraft installations
- 🛡️ **Safe & Secure**: Automatic backups, file verification, hash checking
- 🔍 **CurseForge Integration**: Search and install mods directly from CurseForge
- ⚙️ **Easy Setup**: One-time configuration with persistent settings
- 📦 **Multiple Formats**: Support for text, JSON, and URL-based modlists
- 🌍 **Cross-Platform**: Works perfectly on Windows, macOS, and Linux
- 🎨 **Beautiful Interface**: Rich terminal UI with progress bars and colors

## 🚀 Quick Start

### Option 1: One-Click Installation

1. Download Qwikee
2. Run: `python install.py`
3. Follow the prompts

### Option 2: Manual Installation

```bash
# Install dependencies
pip install requests click rich

# Run Qwikee
python qwikee.py --help
```

### Option 3: Using UV (Recommended)

```bash
# Install using UV
uv tool install . --editable

# Use globally
qwikee --help
```

## 📖 Usage

### Initial Setup

```bash
# Configure API key and default paths
qwikee config --api-key YOUR_CURSEFORGE_API_KEY
qwikee config --mods-path "C:\Users\YourName\.minecraft\mods"
```

### Install Mods

```bash
# Install from modlist
qwikee install my_modlist.txt

# Dry run (preview only)
qwikee install my_modlist.txt --dry-run

# Force overwrite existing files
qwikee install my_modlist.txt --force
```

### Search for Mods

```bash
# Search CurseForge
qwikee search "just enough items"

# Filter by Minecraft version
qwikee search "optifine" --game-version "1.20.1"

# Save results to file
qwikee search "performance mods" --output search_results.txt
```

### Detect Minecraft Installations

```bash
# Find all Minecraft installations
qwikee detect
```

## 📝 Modlist Formats

### Simple Text Format 🚀 Qwikee - Quick Minecraft Mod Installer

A lightning-fast, professional-grade tool for downloading and installing Minecraft mods from CurseForge and direct URLs. Get your mods installed in seconds, not minutes!

## ✨ Features

- ⚡ **Lightning Fast**: Resume interrupted downloads, parallel processing
- 🎯 **Smart Detection**: Automatically finds Minecraft installations
- 🛡️ **Safe & Secure**: Automatic backups, file verification, hash checking
- 🔍 **CurseForge Integration**: Search and install mods directly from CurseForge
- ⚙️ **Easy Setup**: One-time configuration with persistent settings
- 📦 **Multiple Formats**: Support for text, JSON, and URL-based modlists
- 🌍 **Cross-Platform**: Works perfectly on Windows, macOS, and Linux
- 🎨 **Beautiful Interface**: Rich terminal UI with progress bars and colors

## 🚀 Quick Start

### Option 1: One-Click Installation

1. Download Qwikee
2. Run: `python install.py`
3. Follow the prompts

### Option 2: Manual Installation

```bash
# Install dependencies
pip install requests click rich

# Run Qwikee
python qwikee.py --help
```

### Option 3: Using UV (Recommended)

```bash
# Install using UV
uv tool install . --editable

# Use globally
qwikee --help
```

## 📖 Usage

### Initial Setup

```bash
# Configure API key and default paths
qwikee config --api-key YOUR_CURSEFORGE_API_KEY
qwikee config --mods-path "C:\Users\YourName\.minecraft\mods"
```

### Install Mods

```bash
# Install from modlist
qwikee install my_modlist.txt

# Dry run (preview only)
qwikee install my_modlist.txt --dry-run

# Force overwrite existing files
qwikee install my_modlist.txt --force
```

### Search for Mods

```bash
# Search CurseForge
qwikee search "just enough items"

# Filter by Minecraft version
qwikee search "optifine" --game-version "1.20.1"

# Save results to file
qwikee search "performance mods" --output search_results.txt
```

### Detect Minecraft Installations

```bash
# Find all Minecraft installations
qwikee detect
```

## 📝 Modlist Formats

### Simple Text Format
