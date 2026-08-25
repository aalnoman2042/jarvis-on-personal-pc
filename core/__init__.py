"""VONDO's portable core — brains, memory, tools and settings.

Nothing in here may assume it is running on Rohan's desktop. This package is
what gets deployed to the cloud, so it must import cleanly on Linux with no
microphone, no screen and no Windows.

The one deliberate exception is `core.actions`, which still holds the Windows
half of the tool set. It gets split out into the PC agent in phase 03; until
then it is imported lazily by the tool dispatcher and never at package import
time. See CLAUDE.md.
"""
