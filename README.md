<h1 align="center">
  <img src="docs/res/RuK.png#gh-light-mode-only" width="288px"/><br/>
  <img src="docs/res/RuK_dark.png#gh-dark-mode-only" width="288px"/><br/>
</h1>
<p align="center">A simple <b>SuperH Emulator</b> that aim to help understanding SH4.<br/><br/>
Some features like <b>LCD display</b> and <b>Touchscreen</b> are planned, aiming to provide a more native debugging experience !</p>

## Overview
- Memory mapping available
- CPU backtrace on error
- Extensive instruction support, with a flexible code design
- Simple yet useful GUI

## Installation
You'll need Python3. No dependencies are used, simply run the "[test.py](test.py)" and get a simple rom to run OOTB :
````
python3 test.py
````

It should run fine under Windows, Linux, or even MacOS.

Support for binaries and custom ROM are planned. 

## Using the GUI
As RuK is reaching the V1.0, a cool GUI is now work in progress !

![img.png](docs/res/img.png)

This GUI make you able to both take a look at the assembly, and the registers values but also to edit the registers, in real time !
Try to edit the `pc` register value while running the code, and you'll see te magic.

It is also written in TK, using the excellent [rdbende/Sun-Valley-ttk-theme](https://github.com/rdbende/Sun-Valley-ttk-theme) TTK Theme, so do dependencies are expected.

The codebase is still a little messy, but a real clean will be done for the v1.0 !
