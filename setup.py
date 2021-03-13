#!/usr/bin/env python3

from pathlib import Path

from setuptools import setup


def requires(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


setup(
    name         = "mio",
    version      = "0.1.0",
    author       = "miruka",
    author_email = "miruka@disroot.org",
    keywords     = "matrix api chat messaging library",
    # license    = TODO
    # url        = TODO

    description                   = "Experimental Matrix library",
    long_description              = Path("README.md").read_text(),
    long_description_content_type = "text/markdown",

    python_requires  = ">=3.6, <4",
    install_requires = requires("""
        aiofiles          >= 0.6.0,  < 0.7
        aiohttp           >= 3.7.3,  < 4
        phantom-types     >= 0.7.0,  < 0.8
        python-olm        >= 3.1.3,  < 4
        rich              >= 9.13.0, <10
        sortedcollections >= 1.2.1,  < 2
        typingplus        >= 2.2.3,  < 3

        dataclasses       >= 0.6,     < 0.7; python_version<'3.7'
        typing-extensions >= 3.7.4.3, < 4;   python_version<'3.9'
    """),
    extras_require = {
        "dev": requires("""
            flake8                >= 3.8.4,  < 4
            flake8-bugbear        >= 20.1.4, < 21
            flake8-colors         >= 0.1.6,  < 0.2
            flake8-commas         >= 2.0.0,  < 3
            flake8-comprehensions >= 3.3.0,  < 4
            flake8-executable     >= 2.0.4,  < 3
            flake8-isort          >= 4.0.0,  < 5
            flake8-logging-format >= 0.6.0,  < 0.7
            flake8-pie            >= 0.6.1,  < 0.7
            flake8-quotes         >= 3.2.0,  < 4
            mypy                  >= 0.812,  < 0.900
        """),
    },

    classifiers=[
        "Natural Language :: English",
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Environment :: Console",
        "Topic :: Communications :: Chat",

        # ("License :: OSI Approved :: " TODO
         # "GNU Lesser General Public License v3 or later (LGPLv3+)"),

        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
)
