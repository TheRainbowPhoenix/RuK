import ctypes
import os
import sys
import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk
from typing import Dict, Callable
import re

from ruk.gui.preferences import Preferences
from ruk.gui.resources import ResourceManager
from ruk.gui.widgets.base import BaseWrapper, BaseFrame
from ruk.gui.widgets.utils import HookToolTip
from ruk.jcore.cpu import CPU


class ControlsFrame(BaseFrame):
    def __init__(self, cpu: CPU, resources: ResourceManager, **kw):
        super().__init__()
        self._cpu = cpu
        self.resources = resources

        self.continue_until = [
            'Continue until call',
            'Continue until syscall',
            'Continue until breakpoint',
        ]

        self.continue_until_mode = 2  # default: continue until breakpoint
        self.except_pause = 1

        # Run state for non-blocking do_run()
        self._running = False
        self._tk_root = None  # set in hook()

        # Breakpoints: software breakpoints are addresses where the CPU
        # should pause.  Hardware breakpoints use the UBC (max 2).
        self._soft_breakpoints: set = set()
        self._hw_breakpoints: dict = {}  # addr -> channel (0 or 1)

        def noop():
            pass

        self.on_step_callback: Callable = noop
        self.on_stop_callback: Callable = noop
        self.on_breakpoints_callback: Callable = None

    def set_widgets(self, root):
        """
        Setup base widgets
        """

        widget = tk.Frame(root, bd=2)
        widget.pack(fill='both', expand=1)
        self.start_btn = ttk.Button(
            master=widget,
            image=self.resources['start'],
            width=28,
            style="Titlebar.TButton",
            command=self.do_run
        )
        HookToolTip(self.start_btn, "Start")

        self.stop_btn = ttk.Button(
            master=widget,
            image=self.resources['stop'],
            width=28,
            style="Titlebar.TButton",
            command=self.do_stop
        )
        HookToolTip(self.stop_btn, "Stop")

        self.continue_until_btn = ttk.Button(
            widget,
            image=self.resources['continue_until_syscall'],
            width=28,
            style="Titlebar.TButton",
            command=self.continue_until_changed,
        )
        self.continue_until_btn_tooltip = HookToolTip(self.continue_until_btn, "Continue until Syscall")

        self.step_over_btn = ttk.Button(
            master=widget,
            image=self.resources['step_over'],
            width=28,
            style="Titlebar.TButton",
            command=self.do_step_over
        )
        HookToolTip(self.step_over_btn, "Step over")

        self.step_into_btn = ttk.Button(
            master=widget,
            image=self.resources['step_into'],
            width=28,
            style="Titlebar.TButton",
            command=self.do_step_into
        )
        HookToolTip(self.step_into_btn, "Step into")

        self.except_pause_btn = ttk.Button(
            master=widget,
            image=self.resources['except_pause_on'],
            width=28,
            command=self.except_pause_changed,
            style="Titlebar.TButton",
        )
        self.except_pause_btn_tooltip = HookToolTip(self.except_pause_btn, "Pause on exceptions")

        self.breakpoints_btn = ttk.Button(
            master=widget,
            image=self.resources['breakpoints'],
            width=28,
            command=self.do_show_breakpoints,
            style="Titlebar.TButton",
        )
        self.breakpoints_btn_tooltip = HookToolTip(self.breakpoints_btn, "Breakpoints")

        col = 0
        self.start_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.continue_until_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.continue_until_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.step_over_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.step_into_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.stop_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.except_pause_btn.grid(row=0, column=col, padx=2)
        col += 1
        self.breakpoints_btn.grid(row=0, column=col, padx=2)
        col += 1

    def continue_until_changed(self):
        """Cycle through continue-until modes: call -> syscall -> breakpoint."""
        self.continue_until_mode = (self.continue_until_mode + 1) % 3
        if self.continue_until_mode == 0:
            self.continue_until_btn.configure(image=self.resources['continue_until_syscall'])
            self.continue_until_btn_tooltip.text = "Continue until Call"
        elif self.continue_until_mode == 1:
            self.continue_until_btn.configure(image=self.resources['continue_until_syscall'])
            self.continue_until_btn_tooltip.text = "Continue until Syscall"
        else:
            self.continue_until_btn.configure(image=self.resources['continue_until_breakpoint'])
            self.continue_until_btn_tooltip.text = "Continue until Breakpoint"

    def except_pause_changed(self):
        if self.except_pause == 1:
            self.except_pause = 0
            self.except_pause_btn.configure(image=self.resources['except_pause_off'])
            self.except_pause_btn_tooltip.text = "Don't pause on exceptions"
        else:
            self.except_pause = 1
            self.except_pause_btn.configure(image=self.resources['except_pause_on'])
            self.except_pause_btn_tooltip.text = "Pause on exceptions"

    def do_step(self):
        try:
            self._cpu.step()
            self.on_step_callback()
        except Exception as e:
            print(f"!!! CPU Error : {e} !!!")
            self._refresh_callback()
            raise

    def do_step_over(self):
        self.do_step()

    def do_step_into(self):
        self.do_step()

    def do_run(self):
        """Toggle between run and pause.

        When paused (not running), clicking Play starts the CPU running
        in non-blocking batches.  When running, clicking Play pauses the
        CPU so the user can step or inspect.
        """
        if self._running:
            # Already running -> pause
            self._running = False
            self._refresh_callback()
        else:
            # Not running -> start
            self._running = True
            self.start_btn.configure(image=self.resources['pause'])
            self._run_batch()

    def _run_batch(self):
        """Run one batch of CPU steps, then schedule the next batch."""
        if not self._running or self._cpu.ebreak:
            self._running = False
            self.start_btn.configure(image=self.resources['start'])
            self._refresh_callback()
            return

        # Check for software breakpoints before each step
        # (HW breakpoints are handled by the UBC in CPU.step)
        batch_size = 500
        for _ in range(batch_size):
            if self._cpu.ebreak:
                break

            # Check software breakpoints
            if hasattr(self, '_soft_breakpoints') and self._cpu.pc in self._soft_breakpoints:
                # Hit a software breakpoint -> pause
                self._running = False
                self.start_btn.configure(image=self.resources['start'])
                self._refresh_callback()
                return

            try:
                self._cpu.step()
            except Exception as e:
                print(f"!!! CPU Error : {e} !!!")
                self._running = False
                self.start_btn.configure(image=self.resources['start'])
                self._refresh_callback()
                return

        # Periodically refresh the GUI (every batch)
        self._refresh_callback()

        # Schedule the next batch using after() so the GUI stays responsive
        if self._tk_root is not None:
            self._tk_root.after(1, self._run_batch)
        else:
            # Fallback: run synchronously (blocks GUI but works)
            self._run_batch()

    def do_stop(self):
        """Stop and reset the CPU."""
        self._running = False
        self.start_btn.configure(image=self.resources['start'])
        self._cpu.reset()
        self.on_stop_callback()

    def hook(self, root: tk.Frame):
        self.set_widgets(root)
        # Store the tk root for after() scheduling in do_run()
        # root is a tk.Frame, so its master (or root itself if it's a Tk) is the root
        try:
            self._tk_root = root.winfo_toplevel()
        except:
            self._tk_root = None

    def refresh(self):
        pass

    # ---- Breakpoint management ----

    def add_soft_breakpoint(self, addr: int):
        """Add a software breakpoint at the given address."""
        if not hasattr(self, '_soft_breakpoints'):
            self._soft_breakpoints = set()
        self._soft_breakpoints.add(addr & 0xFFFFFFFF)

    def remove_soft_breakpoint(self, addr: int):
        """Remove a software breakpoint."""
        if hasattr(self, '_soft_breakpoints'):
            self._soft_breakpoints.discard(addr & 0xFFFFFFFF)

    def toggle_soft_breakpoint(self, addr: int) -> bool:
        """Toggle a software breakpoint.  Returns True if now set."""
        if not hasattr(self, '_soft_breakpoints'):
            self._soft_breakpoints = set()
        addr &= 0xFFFFFFFF
        if addr in self._soft_breakpoints:
            self._soft_breakpoints.discard(addr)
            return False
        else:
            self._soft_breakpoints.add(addr)
            return True

    def add_hw_breakpoint(self, addr: int) -> int:
        """Add a hardware breakpoint via the UBC.

        Returns the channel number (0 or 1), or -1 if both channels
        are in use.
        """
        if not hasattr(self, '_hw_breakpoints'):
            self._hw_breakpoints = {}
        addr &= 0xFFFFFFFF
        # Check if already set
        for a, ch in self._hw_breakpoints.items():
            if a == addr:
                return ch
        # Find a free channel
        used_channels = set(self._hw_breakpoints.values())
        for ch in range(2):
            if ch not in used_channels:
                self._hw_breakpoints[addr] = ch
                # Configure the UBC
                if self._cpu.ubc is not None:
                    self._cpu.ubc.set_breakpoint(ch, addr)
                return ch
        return -1  # both channels in use

    def remove_hw_breakpoint(self, addr: int):
        """Remove a hardware breakpoint."""
        if hasattr(self, '_hw_breakpoints'):
            addr &= 0xFFFFFFFF
            if addr in self._hw_breakpoints:
                ch = self._hw_breakpoints.pop(addr)
                if self._cpu.ubc is not None:
                    self._cpu.ubc.clear_breakpoint(ch)

    def get_all_breakpoints(self):
        """Return a dict of all breakpoints: {addr: 'soft' or 'hw'}."""
        result = {}
        if hasattr(self, '_soft_breakpoints'):
            for addr in self._soft_breakpoints:
                result[addr] = 'soft'
        if hasattr(self, '_hw_breakpoints'):
            for addr in self._hw_breakpoints:
                result[addr] = 'hw'
        return result

    def clear_all_breakpoints(self):
        """Remove all breakpoints."""
        if hasattr(self, '_soft_breakpoints'):
            self._soft_breakpoints.clear()
        if hasattr(self, '_hw_breakpoints'):
            for addr in list(self._hw_breakpoints.keys()):
                self.remove_hw_breakpoint(addr)

    def do_show_breakpoints(self):
        """Show the breakpoints window.

        This calls the on_breakpoints_callback if set, which opens the
        breakpoints window in the main DebuggerWindow.
        """
        if hasattr(self, 'on_breakpoints_callback') and self.on_breakpoints_callback is not None:
            self.on_breakpoints_callback()
        else:
            # Print current breakpoints as fallback
            bps = self.get_all_breakpoints()
            if not bps:
                print("No breakpoints set")
            else:
                print("Breakpoints:")
                for addr, btype in sorted(bps.items()):
                    print(f"  0x{addr:08X} ({btype})")
