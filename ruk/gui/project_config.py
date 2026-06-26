"""
Project configuration for RuK emulator.

Stores and loads project configurations (ROM path, add-in paths, start PC, etc.)
in a cross-platform location:
  - Windows: %APPDATA%/RuK/projects.json
  - macOS:   ~/Library/Application Support/RuK/projects.json
  - Linux:   ~/.config/RuK/projects.json
"""

import json
import os
import time
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class AddIn:
    """A program to load into memory alongside the ROM."""
    path: str = ""
    load_addr: int = 0x8CFF0000
    description: str = ""


@dataclass
class Project:
    """A RuK emulator project configuration."""
    name: str = "Untitled"
    rom_path: str = ""
    start_pc: int = 0x80000000
    sr_value: int = 0x400001F0
    addins: List[AddIn] = field(default_factory=list)
    with_tmu: bool = True
    with_rtc: bool = True
    with_dma: bool = True
    with_display: bool = True
    with_ubc: bool = True
    last_opened: float = 0.0
    is_assembly: bool = False  # True if rom_path is an .asm file to assemble

    def to_dict(self) -> dict:
        d = asdict(self)
        d['start_pc'] = f"0x{self.start_pc:08X}"
        d['sr_value'] = f"0x{self.sr_value:08X}"
        for a in d['addins']:
            a['load_addr'] = f"0x{a['load_addr']:08X}"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'Project':
        def parse_addr(v):
            if isinstance(v, str):
                return int(v, 0)
            return v
        return cls(
            name=d.get('name', 'Untitled'),
            rom_path=d.get('rom_path', ''),
            start_pc=parse_addr(d.get('start_pc', 0x80000000)),
            sr_value=parse_addr(d.get('sr_value', 0x400001F0)),
            addins=[AddIn(path=a.get('path', ''),
                          load_addr=parse_addr(a.get('load_addr', 0x8CFF0000)),
                          description=a.get('description', ''))
                    for a in d.get('addins', [])],
            with_tmu=d.get('with_tmu', True),
            with_rtc=d.get('with_rtc', True),
            with_dma=d.get('with_dma', True),
            with_display=d.get('with_display', True),
            with_ubc=d.get('with_ubc', True),
            last_opened=d.get('last_opened', 0.0),
            is_assembly=d.get('is_assembly', False),
        )


def get_config_dir() -> str:
    """Get the cross-platform config directory for RuK."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    elif sys.platform == 'darwin':
        base = os.path.expanduser('~/Library/Application Support')
    else:
        base = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
    return os.path.join(base, 'RuK')


import sys  # needed by get_config_dir on some platforms


def get_projects_file() -> str:
    """Get the path to the projects JSON file."""
    return os.path.join(get_config_dir(), 'projects.json')


def load_projects() -> List[Project]:
    """Load the list of recent projects from disk."""
    path = get_projects_file()
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        return [Project.from_dict(p) for p in data.get('projects', [])]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def save_projects(projects: List[Project]):
    """Save the list of projects to disk."""
    config_dir = get_config_dir()
    os.makedirs(config_dir, exist_ok=True)
    path = get_projects_file()
    data = {
        'projects': [p.to_dict() for p in projects],
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def add_or_update_project(project: Project):
    """Add a project to the recent list (or update if it exists)."""
    projects = load_projects()
    # Remove duplicate (same name + rom_path)
    projects = [p for p in projects if not (p.name == project.name and p.rom_path == project.rom_path)]
    project.last_opened = time.time()
    projects.insert(0, project)
    # Keep only the last 20 projects
    projects = projects[:20]
    save_projects(projects)


def remove_project(project: Project):
    """Remove a project from the recent list."""
    projects = load_projects()
    projects = [p for p in projects if not (p.name == project.name and p.rom_path == project.rom_path)]
    save_projects(projects)
