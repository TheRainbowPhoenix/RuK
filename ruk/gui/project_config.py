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
import sys
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
    with_touch: bool = True
    is_assembly: bool = False  # True if rom_path is an .asm file to assemble
    last_opened: float = 0.0
    # HH3-specific: if set, this project loads an .hh3 addin via the ELF loader
    hh3_path: str = "" 

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
            with_touch=d.get('with_touch', True),
            last_opened=d.get('last_opened', 0.0),
            is_assembly=d.get('is_assembly', False),
        	hh3_path=d.get('hh3_path', ''),
        )


def get_config_dir() -> str:
    """Get the cross-platform config directory for RuK."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        d = os.path.join(base, 'RuK')
    elif sys.platform == 'darwin':
        d = os.path.expanduser('~/Library/Application Support/RuK')
    else:
        base = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        d = os.path.join(base, 'RuK')
    os.makedirs(d, exist_ok=True)
    return d


def get_projects_file() -> str:
    """Get the path to the projects JSON file."""
    return os.path.join(get_config_dir(), 'projects.json')


# ============================================================================
# Load / save
# ============================================================================


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


def save_projects(projects: List[Project]) -> None:
    """Save the projects list to disk."""
    f = get_projects_file()
    data = {'projects': [Project.to_dict(p) for p in projects]}
    with open(f, 'w') as fp:
        json.dump(data, fp, indent=2)


# ============================================================================
# Mutations
# ============================================================================

def add_or_update_project(project: Project) -> None:
    """Add or update a project (matched by name).  Updates last_opened."""
    project.last_opened = time.time()
    projects = load_projects()
    for i, p in enumerate(projects):
        if p.name == project.name:
            projects[i] = project
            save_projects(projects)
            return
    projects.append(project)
    save_projects(projects)


def remove_project(project: Project):
    """Remove a project from the recent list."""
    projects = load_projects()
    projects = [p for p in projects if not (p.name == project.name and p.rom_path == project.rom_path)]
    save_projects(projects)
