# CHANGELOG

## F.E.D.O v1.3 — Stable GUI & Hybrid AI Update

### Added
- Added new CustomTkinter GUI architecture.
- Added top navigation tabs: Chat, PC, Memory, Settings.
- Added Developer Mode with Terminal, Logs and Debug tabs.
- Added hidden aggressive personality unlock via 5 clicks on F.E.D.O title.
- Added Gemini API Key field in Settings.
- Added LM Studio URL field in Settings.
- Added GPU / VRAM monitoring through GPUtil.
- Added system metrics for CPU, RAM and Disk.
- Added temporary aggressive mode reset on application restart.

### Improved
- Improved GUI structure and readability.
- Improved Apple-clean + terminal-core visual style.
- Improved settings organization.
- Improved system monitor layout.
- Improved AI status display.
- Improved project stability after GUI cleanup.

### Fixed
- Removed broken duplicated GUI methods.
- Fixed missing `_update_ai_status` method.
- Fixed Developer Mode tab rebuilding.
- Fixed aggressive mode visibility logic.
- Fixed requirements cleanup by removing `.gitignore` entries from dependency list.

### Known Issues
- Hotkeys Ctrl+A / Ctrl+C / Ctrl+V may behave inconsistently on some Windows keyboard layouts.
- Context menu support is being added as a more stable replacement.