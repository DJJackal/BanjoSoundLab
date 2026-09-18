Banjo Sound Lab

Banjo Sound Lab is a portable Windows application for exploring audio from a user-supplied Banjo-Kazooie ROM. It can extract the game's sound library, search and preview individual sounds, and render music tracks locally without distributing the ROM or extracted game audio.

Features

Extracts 734 sounds from a supported Banjo-Kazooie ROM

Searchable sound library

Sound preview and playback

Music-track rendering directly from the user's ROM

Improved loop handling to reduce clicks and rain-like artefacts

Short attack and release ramps for cleaner voice playback

Catmull-Rom interpolation for cleaner resampling

Portable library stored beside the application when possible

No Python installation required

Download and use

Download Banjo Sound Lab.exe from the Releases page.

Place it in its own writable folder.

Double-click the executable.

When prompted, select your own legally obtained Banjo-Kazooie ROM.

Allow the initial extraction to complete.

The application creates its working library beside the executable. If that location is not writable, it uses %LOCALAPPDATA%\BanjoSoundLab instead.

Keep the selected ROM in its original location. Music is rendered from the ROM when requested and is not bundled with the application.

Windows SmartScreen

The executable is not code-signed, so Windows may display a Windows protected your PC warning on first launch. If you downloaded it from this repository, select More info, then Run anyway.

The warning does not mean that malware was detected. It appears because the application is from an unknown publisher. You should still download releases only from this repository.

What is not included

This project does not contain or distribute:

A Banjo-Kazooie ROM

Extracted sound effects, music or other game assets

Nintendo or Rare proprietary code

You must provide your own legally obtained ROM. Do not upload ROMs or extracted copyrighted assets when reporting an issue.

Building from source

The source version requires a current Python 3 installation. Install the project dependencies, then run:

py package.py

This creates the single-file Windows executable. To create the source archive instead, run:

py package.py --zip

Known limitations

Windows only

First launch may take a few seconds while the one-file executable unpacks

The ROM must remain available for on-demand music rendering

Compatibility may depend on the ROM version and dump quality

Legal notice

Banjo Sound Lab is an unofficial fan-made utility and is not affiliated with, endorsed by or sponsored by Nintendo, Rare or Microsoft.

Banjo-Kazooie and all related names, characters, music, sound effects and game assets are the property of their respective owners. This repository's licence applies only to the original Banjo Sound Lab source code and does not grant rights to any third-party material.

Licence

The original source code in this repository is released under the MIT Licence. Third-party components remain subject to their own licences.
