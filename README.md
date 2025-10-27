# Yertz Advanced Personal Reporter (YAPR)

A realtime GUI radar and activity tracker for Star Citizen that parses your Game.log file to provide situational awareness and statistics tracking based on advanced adaptive logic filtering. This advanced logic will also work for future unreleased content.

![Star Citizen Version](https://img.shields.io/badge/Star%20Citizen-4.0+-blue)
![Python Version](https://img.shields.io/badge/Python-3.7+-green)
![Static Badge](https://img.shields.io/badge/Yertz_and_Yertz-Yertz?color=blue&link=https%3A%2F%2Fgithub.com%2Fscubamount)


## Showcase
<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/7f43ffb8-155b-4ae3-8370-513d7f4cc177" />
<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/262e964d-7eb1-44e9-8560-8ca812c9663a" />


## Features

### 🎯 Real-Time Radar Display
- **Visual radar interface** showing nearby players, vehicles, and transit activity
- **Dynamic zoom** with mouse wheel to adjust viewing distance
- **Auto-centering** on your position with distance rings (25m, 50m, 100m, 250m, 500m)
- **Dark/Light mode** toggle for comfortable viewing
- **Color-coded markers** for different entity types
- **Optimized layout** with radar taking less space for better information visibility

### 👥 Player Detection & Tracking
- **Automatic player detection** from game logs
- **Live player status tracking** (Alive, Dead, Incapacitated)
- **Spawn reset detection** - know when players respawn
- **Player activity timeline** showing when players were last seen
- **Hostility detection** - tracks combat interactions between players
- **Dedicated player list panel** with real-time status updates
- **Smart scroll persistence** - manually scroll through player list without auto-scroll interruption

### 🚗 Vehicle Monitoring
- **Vehicle detection** when vehicles spawn nearby
- **Destruction tracking** with three states:
  - Alive (fully operational)
  - Softed (damaged but operational)
  - FullDead (destroyed)
- **Attacker identification** - see who destroyed which vehicle
- **Vehicle entry/exit tracking** - displays your current vehicle
- **Dedicated vehicle panel** with status history

### 🏢 Transit & Location Tracking
- **Elevator/transit system monitoring** (doors, carriages, lifts)
- **Dungeon entrance/exit detection** with customizable alerts
- **Zone detection** - automatically identifies your current location
- **Landing zone tracking** - detects station arrivals
- **Transit association** - links nearby players with transit activity

### 📊 Statistics & Kill Tracking
- **Persistent kill statistics** saved across sessions in `yapr_export.json`
  - Total kills (all-time)
  - Session kills (current server session)
  - Separate tracking for Player kills vs NPC kills
- **Dedicated Kill Tracking Panels:**
  - **Player Kills Column**: Alphabetically sorted list of all players you've eliminated
  - **NPC Kills Column**: Session and total NPC kill counts
- **Kill location tracking** with radar visualization
- **Kill distance and position logging**
- **Statistics survive application restarts** - data automatically loads on startup
- **JSON export** of all statistics and detected zones

### 🔔 Alerts & Notifications
- **Optional sound alerts** for dungeon entrances
- **Visual flash indicators** for new detections
- **Age-based color fading** - newer pings are brighter
- **Priority-based ping management** - important events stay visible longer

### 🔍 Advanced Detection
- **Server swap detection** - automatically clears radar when changing servers
- **Spawn flow tracking** - monitors player respawn events
- **Corpse detection** - tracks player deaths
- **Incapacitation events** - shows when players go down
- **Entity attachment tracking** - advanced player detection
- **Improved blacklist filtering** - eliminates false player detections (doors, NPCs, system entities)

### 📁 Data Export
- **Automatic JSON export** to `yapr_export.json`
- **Exports include:**
  - Kill statistics (total, NPCs, players)
  - Unique players encountered
  - Players you've killed (persistent list)
  - All detected zones and transit locations
  - Last updated timestamp
  - Player name and game version

## Installation

### Requirements
- Python 3.7 or higher
- Star Citizen installed
- Windows OS (uses `winsound` for alerts)

### Setup

1. **Clone the repository:**
```bash
git clone https://github.com/scubamount/YAPR.git
cd yapr
```

2. **Configure the log path (if needed):**
Edit `yapr.py` and update the `LOG_PATH` variable:
```python
LOG_PATH = r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log"
```

## Usage

### Running the Application
```bash
python yapr.py
```

Or if you have the compiled executable:
```bash
yapr.exe
```

### Interface Overview

#### Main Radar Window (Left)
- **Center dot (Green)**: Your position
- **Colored dots**: Detected entities
  - **Yellow**: Players
  - **Cyan**: Transit/Elevator activity
  - **Magenta**: Dungeon entrances/exits
  - **Orange**: NPC kills
  - **Red**: Player kills
  - **Green**: Vehicles
  - **White**: New/fresh detections
- **Distance rings**: Show scale (25m, 50m, 100m, 250m, 500m)
- **Zoom level**: Displayed in top left
- **Compact size**: Radar uses 1/3 of window width for better panel visibility

#### Side Panel (Right)

**Recent Events Log**
- Shows all detected events in chronological order
- Color-coded by event type
- Includes timestamps and position data
- **Smart scroll**: Stays at your scroll position until you return to top

**Four-Column Layout:**

1. **Detected Players** (Left Column)
   - List of all players encountered
   - Shows status (alive, dead, incapacitated)
   - Time since last seen
   - Spawn reset indicators
   - Color-coded by status and age

2. **Player Kills** (Middle-Left Column)
   - **NEW**: Dedicated list of players you've killed
   - Alphabetically sorted
   - Shows total kill count
   - Persists across sessions

3. **Nearby Vehicles** (Middle-Right Column)
   - Active vehicles in the area
   - Destruction state tracking
   - Who destroyed which vehicle
   - Time since last update

4. **NPC Kills** (Right Column)
   - **NEW**: Session NPC kill count
   - Total lifetime NPC kills
   - Statistics persist across sessions

#### Menu Options

**Options > Dark Mode**
- Toggle between dark and light themes

**Options > Dungeon Sound Alert**
- Enable/disable audio alerts for dungeon entrances

### Controls

- **Mouse Wheel**: Zoom in/out on the radar
- **Window Resize**: Interface properly scales, radar stays proportional (1:3 ratio)
- **Scroll in any text panel**: Position persists until you scroll back to top

## Configuration

### Adjustable Constants (in code)
```python
ENTITY_TIMEOUT = 580.0              # How long entities stay on radar
PING_LIFETIME = 45.0                # Standard ping duration
DUNGEON_PING_LIFETIME = 120.0       # Dungeon ping duration
NPC_KILL_LIFETIME = 45.0            # Kill marker duration
VEHICLE_TIMEOUT = 300.0             # Vehicle tracking timeout
INITIAL_SCALE = 1.2                 # Starting zoom level
SOUND_COOLDOWN = 3.0                # Seconds between sound alerts
```

### Manager Aliases

The application includes friendly names for common transit locations:
- Hangar ↔ Lobby elevators
- Ghost Arena entrances (A, B, C)
- Dungeon entrances and exits
- Station lifts and transit systems

## Features in Detail

### Kill Tracking
The application tracks two types of kills:
- **NPC Kills**: Any AI enemies you eliminate
- **Player Kills**: PvP combat victories (with names)

Statistics are:
- **Saved persistently** to `yapr_export.json` across sessions
- Exported automatically every 60 seconds
- Updated in real-time in dedicated UI columns
- **Automatically loaded on startup** - your kill history is never lost
- Session counters reset per server, lifetime totals persist forever

### Vehicle Destruction States
1. **Alive (0)**: Vehicle is fully functional
2. **Softed (1)**: Vehicle is damaged but operational
3. **FullDead (2)**: Vehicle is completely destroyed

### Auto-Detection
The app automatically detects:
- Your player name from login events
- Game version from command-line parameters
- Your player ID/GEID for accurate self-filtering

### Server Swap Handling
When you change servers, the application:
- Attempts to detect the server swap automatically
- Clears temporary radar data
- **Preserves persistent statistics** (total kills remain intact)
- Resets session kill counters for new server

### Smart Scroll Behavior
All text panels feature intelligent scrolling:
- **Auto-scroll when at top**: New content automatically appears
- **Manual scroll persistence**: Scroll down to read, position stays locked
- **Resume auto-scroll**: Scroll back to top to re-enable auto-updates
- Works on all panels: Events, Players, Vehicles, and Kill lists

## Export Format

The `yapr_export.json` file contains:
```json
{
  "last_updated": "2025-01-22T22:20:31.123456+00:00",
  "player_name": "YourPlayerName",
  "game_version": "4.0",
  "total_kills": 150,
  "npc_kills": 145,
  "player_kills": 5,
  "unique_transits": ["HangarLobby", "Ghost Arena A", ...],
  "unique_players": ["Player1", "Player2", ...],
  "players_killed": ["Victim1", "Victim2", ...],
  "detected_zones": ["Stanton", "Pyro", ...]
}
```

## Recent Updates

### Latest Improvements
- **Four-column layout** for better information density
- **Dedicated kill tracking panels** for Player Kills and NPC Kills
- **Persistent kill statistics** that survive application restarts
- **Optimized radar size** (now 1/3 of window width vs 1/2)
- **Better window resizing** with proper proportions (radar:panel = 1:3)
- **Smart scroll persistence** across all text panels
- **Improved player detection** with enhanced blacklist filtering
- **Player kill names** now stored and displayed in dedicated column

## Known Limitations

- **Windows Only**: Uses Windows-specific sound library
- **Game.log Required**: Star Citizen must generate the log file
- **Position Accuracy**: Depends on log data availability
- **English Logs**: Primarily designed for English game client

## Troubleshooting

### "Game.log Not Found" Error
- Ensure Star Citizen is installed
- Check the `LOG_PATH` in the script matches your installation
- The game must be running to generate the log file

### Players Not Appearing
- The application uses multiple detection methods
- Some players may only appear when they perform actions
- Close proximity is required for most detections

### Radar Not Updating
- Check if the Game.log file is being updated
- Restart Star Citizen if the log has stalled
- Verify file permissions on the log directory

### Kill Statistics Not Loading
- Ensure `yapr_export.json` is in the same directory as the application
- Check file permissions on the export file
- Statistics will be created automatically if file is missing

## Contributing

Please feel free to submit pull requests or open issues for bugs and feature requests.

### Development

The codebase is organized into several sections:
- **CONFIG**: Configuration constants
- **REGEX PATTERNS**: Log parsing patterns
- **SHARED STATE**: Application state management
- **HELPERS**: Utility functions
- **FILE TAILER**: Log file reader
- **PARSER**: Main log parsing logic
- **UI**: Tkinter interface with responsive layout

## License

ALL RIGHTS RESERVED

## Support the author

SC Referral code: `STAR-X9TD-9G29`

https://www.patreon.com/dotyerts

https://ko-fi.com/yerts

## Disclaimer

This tool only reads the Game.log file and does not modify any game files or memory. It provides no gameplay advantages beyond what's visible in the log file. Use at your own discretion.

---

**Star Citizen** is a trademark of Cloud Imperium Games Corporation.
