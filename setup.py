from setuptools import setup, find_packages

setup(
    name="terminal-lyrics",
    version="0.1.0",
    description="Display synchronized lyrics in your terminal, fetched automatically for the song playing in your MPRIS-compatible music player",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    python_requires=">=3.10",
    license="MIT",
    author="karst3nz",
    url="https://github.com/karst3nz/terminal_lyrics",
    packages=find_packages(),
    package_data={"terminal_lyrics": ["py.typed"]},
    install_requires=[
        "colorama",
        "regex",
        "dbus-python",
        "requests",
        "typer",
    ],
    extras_require={
        "dev": [
            "pytest",
            "black",
            "ruff",
            "mypy",
        ]
    },
    entry_points={
        "console_scripts": [
            "terminal-lyrics=terminal_lyrics.cli:main",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Sound/Audio",
        "Topic :: Utilities",
    ],
    keywords="lyrics terminal mpris music lrc synchronized",
)
