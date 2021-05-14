# Soft-MDC
MDC import through DCS-BIOS for the F-16

## Pre-Requisites
- Install DCS-BIOS ( https://github.com/dcs-bios/dcs-bios/releases )
- Run DCS-BIOS-HUB and open DCS-BIOS-Webinterface (right-click systray icon).
- Install module-f-16c-50 plugin under "Plugins" / "Open plugin catalog"
- Go to "DCS-Connection" and enable checkboxes for "Virtual Cockpit Connection" and "Autostart DCS-BIOS"
- Verify that the LUA-commands shown in the box are in your SavedGames-folder's export.lua

## How to run this app
- Receive JSON-file from your flightlead / mission planner
- Drag JSON-file containing the MDC data onto the softmdc.exe and launch DCS.
- When ready to get MDC data input into your F-16, set Master-ARM to SIM. This will start the process.
- Do not fiddle with the IFC while inputting is in progress. Instead use your time while waiting for your INS to align or whatever.

## How to use as mission planner / flightlead
- Either create a JSON-file from scratch
- Or use the "-e" commandline option to extract waypoints of a flight from a MIZ-File. Just plan your mission, extract to JSON and then distribute to your flight.
- Other options will be asked of you as you run this tool with the "-e" option.
