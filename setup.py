from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="minecraft-mod-manager",
    version="1.0.0",
    author="Diego Gaytan",
    author_email="diegogaytan2000@gmail.com",
    description="A CLI tool for managing Minecraft mods",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/DGSENZEN/qwikee",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.8",
    install_requires=[
        "click>=8.0.0",
        "rich>=13.0.0",
        "httpx>=0.24.0",
    ],
    entry_points={
        "console_scripts": [
            "mcmod=mcmod.cli:main",
        ],
    },
)
