#!/usr/bin/env python3
"""
One-click installer for Qwikee - Quick Minecraft Mod Installer
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

def install_package():
    """Install Qwikee package"""
    print("🚀 Installing Qwikee - Quick Minecraft Mod Installer...")
    
    # Check if Python 3.8+ is available
    if sys.version_info < (3, 8):
        print("❌ Error: Python 3.8 or higher is required")
        print("Please install Python 3.8+ and try again")
        return False
    
    try:
        # Install using pip
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", ".",
            "--user", "--upgrade"
        ])
        
        print("✅ Installation complete!")
        print("\nYou can now use Qwikee with:")
        print("  qwikee --help")
        print("  qwikee config --api-key YOUR_API_KEY")
        print("  qwikee install your_modlist.txt")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Installation failed: {e}")
        return False

def create_desktop_shortcut():
    """Create desktop shortcut (Windows only)"""
    if platform.system() != "Windows":
        return
    
    try:
        import winshell
        from win32com.client import Dispatch
        
        desktop = winshell.desktop()
        shortcut_path = os.path.join(desktop, "Qwikee.lnk")
        
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = sys.executable
        shortcut.Arguments = "-m qwikee"
        shortcut.WorkingDirectory = os.path.dirname(sys.executable)
        shortcut.IconLocation = sys.executable
        shortcut.save()
        
        print("✅ Desktop shortcut created")
        
    except ImportError:
        print("ℹ️  Install pywin32 for desktop shortcut support")
    except Exception as e:
        print(f"⚠️  Could not create desktop shortcut: {e}")

if __name__ == "__main__":
    if install_package():
        create_desktop_shortcut()
        
        print("\n🎉 Qwikee setup complete!")
        print("Run 'qwikee --help' to get started")
