# setup.py
from setuptools import setup, find_packages

setup(
    name="minecraft-mod-manager",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.0.0",
        "rich>=13.0.0",
        "httpx>=0.24.0",
    ],
    entry_points={
        "console_scripts": [
            "mcmod=mod_manager:main",
        ],
    },
    author="Diego Gaytan",
    description="A CLI tool for managing Minecraft mods",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/DGSENZEN/qwikee",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
)
