#!/usr/bin/env python3
"""
One-click installer for Qwikee using UV
Author: Diego Gaytan
"""

import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path

def check_uv_installed():
    """Check if UV is installed"""
    try:
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ UV is installed: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    return False

def install_uv():
    """Install UV if not already installed"""
    print("📦 Installing UV...")
    
    try:
        if platform.system() == "Windows":
            # Windows installation
            subprocess.check_call([
                "powershell", "-Command", 
                "irm https://astral.sh/uv/install.ps1 | iex"
            ])
        else:
            # Unix-like systems (macOS, Linux)
            subprocess.check_call([
                "bash", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"
            ])
        
        print("✅ UV installed successfully!")
        
        # Add UV to PATH for current session
        uv_bin_path = Path.home() / ".cargo" / "bin"
        if uv_bin_path.exists():
            os.environ["PATH"] = f"{uv_bin_path}:{os.environ.get('PATH', '')}"
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install UV automatically: {e}")
        print("\n🛠️  Manual installation:")
        if platform.system() == "Windows":
            print("  powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\"")
        else:
            print("  curl -LsSf https://astral.sh/uv/install.sh | sh")
        print("  Or visit: https://github.com/astral-sh/uv")
        return False

def install_qwikee_with_uv():
    """Install Qwikee using UV"""
    print("🚀 Installing Qwikee with UV...")
    
    try:
        # Method 1: Install as a tool (recommended)
        print("📦 Installing Qwikee as a tool...")
        result = subprocess.run(["uv", "tool", "install", "."], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Qwikee installed successfully as a tool!")
            print("\n🎉 You can now use Qwikee with:")
            print("  qwikee --help")
            print("  qwikee config --api-key YOUR_KEY")
            print("  qwikee install modlist.txt")
            
            # Check UV tools path
            show_path_info()
            return True
        else:
            print("⚠️  Tool installation failed, trying alternative method...")
            
    except subprocess.CalledProcessError:
        print("⚠️  Tool installation failed, trying alternative method...")
    
    # Method 2: Install in current environment
    try:
        print("📦 Installing Qwikee in current environment...")
        subprocess.check_call(["uv", "pip", "install", "."])
        
        print("✅ Qwikee installed successfully!")
        print("Run: python3 -m qwikee --help")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Installation failed: {e}")
        return False

def show_path_info():
    """Show PATH information for UV tools"""
    # Common UV tool paths
    possible_paths = [
        Path.home() / ".local" / "bin",
        Path.home() / ".cargo" / "bin",
        Path("/usr/local/bin"),
    ]
    
    uv_tools_path = None
    for path in possible_paths:
        if path.exists() and (path / "qwikee").exists():
            uv_tools_path = path
            break
    
    if uv_tools_path:
        print(f"\n📝 Qwikee installed to: {uv_tools_path}")
        
        # Check if it's in PATH
        current_path = os.environ.get("PATH", "")
        if str(uv_tools_path) not in current_path:
            print("⚠️  UV tools directory not in PATH!")
            print("Add this to your shell configuration (.bashrc, .zshrc, etc.):")
            print(f'export PATH="$PATH:{uv_tools_path}"')
            print("\nOr reload your shell configuration:")
            print("  source ~/.bashrc  # or ~/.zshrc")

def test_installation():
    """Test if Qwikee is working"""
    print("\n🧪 Testing installation...")
    
    # Test 1: Try running qwikee directly
    try:
        result = subprocess.run(["qwikee", "--help"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ Qwikee command working!")
            return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # Test 2: Try running with python -m
    try:
        result = subprocess.run([sys.executable, "-m", "qwikee", "--help"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ Qwikee module working!")
            print("Use: python3 -m qwikee --help")
            return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    
    # Test 3: Try running the script directly
    if Path("qwikee.py").exists():
        try:
            result = subprocess.run([sys.executable, "qwikee.py", "--help"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print("✅ Qwikee script working!")
                print("Use: python3 qwikee.py --help")
                return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    
    print("⚠️  Installation test failed")
    return False

def main():
    """Main installation function"""
    print("🚀 Qwikee - Quick Minecraft Mod Installer Setup")
    print("   by Diego Gaytan")
    print("=" * 50)
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Error: Python 3.8 or higher is required")
        print(f"Current version: {sys.version}")
        return False
    
    print(f"✅ Python {sys.version.split()[0]} detected")
    
    # Check if UV is installed
    if not check_uv_installed():
        if not install_uv():
            return False
    
    # Install Qwikee with UV
    if not install_qwikee_with_uv():
        return False
    
    # Test installation
    test_installation()
    
    print("\n🎉 Qwikee setup complete!")
    print("📖 Quick start:")
    print("  1. Get a CurseForge API key: https://console.curseforge.com")
    print("  2. Configure: qwikee config --api-key YOUR_KEY")
    print("  3. Install mods: qwikee install modlist.txt")
    print("\nHappy modding! 🎮")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n👋 Installation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        sys.exit(1)
