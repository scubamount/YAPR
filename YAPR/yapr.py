# ==============================================================================
# YERTZ ADVANCED PERSONAL REPORTER
# ==============================================================================
# Enhanced features:
# - Vehicle destruction tracking (0=Alive, 1=Softed, 2=FullDead)
# - Vehicle detection via fuel controller lambda patterns
# - Improved player detection with relaxed rules
# - Dynamic window resizing with radar recentering
# - Enhanced color transitions for ping aging
# - Current vehicle display under player name
# - Auto-detect player name and game version from full log scan
# - Persistent kill tracking across sessions
# ==============================================================================

import threading
import time
import re
import collections
import queue
import os
import json
import math
import sys
from datetime import datetime, timezone
try:
    import winsound
except Exception:
    winsound = None

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, font
except Exception:
    raise SystemExit("Tkinter required (run on desktop with display).")

# ---------------- CONFIG ----------------
LOG_PATH = r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log"

# Get the directory where the executable is located (works for both .py and .exe)
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    APPLICATION_PATH = os.path.dirname(sys.executable)
else:
    # Running as script
    APPLICATION_PATH = os.path.dirname(os.path.abspath(__file__))
EXPORT_LOG_PATH = os.path.join(APPLICATION_PATH, "yapr_export.json")
PLAYER_NAME = "Unknown"  # Will be auto-detected
GAME_VERSION = "Unknown"  # Will be auto-detected
TAIL_SLEEP = 0.12
ENTITY_TIMEOUT = 580.0
PING_LIFETIME = 45.0
DUNGEON_PING_LIFETIME = 120.0
NPC_KILL_LIFETIME = 45.0
PING_FLASH_WINDOW = 2.5
INITIAL_SCALE = 1.2
STACK_OFFSET_PX = 20
PLAYER_TRANSIT_ASSOCIATION_WINDOW = 20.0
MAX_PINGS_PER_MANAGER = 3
SOUND_COOLDOWN = 3.0
PLAYER_DOT_RADIUS = 8
PLAYER_DOT_RADIUS_INNER = 6
MAX_ZONE_MENTIONS_DISPLAY = 5
EXIT_PING_LIFETIME = 30.0
DUPLICATE_PING_WINDOW = 10.0
VEHICLE_TIMEOUT = 300.0

landing_door_re = re.compile(r'LandingArea.*- Door:\s*([^,\]]+)[\],].*State:\s*([A-Za-z]+)', re.IGNORECASE)
exit_event_re = re.compile(r'\bExit Event\b', re.IGNORECASE)

PLAYER_NAME_BLACKLIST = {
    "team_gameservices", "insured", "instance", "game", "localclient",
    "telemetryservice", "networkbinding", "streamengine", "physicssystem",
    "default", "persistentstreamingservice", "loadoutservice", "server", "requested", "haptic", "[team_gameservices][haptic]",
    "elevator", "npc kill", "player kill", "npc_kill", "player_kill", "door", "hangardoor", "lobbydoor", "landingarea",
    "carriage", "manager", "habs", "lobby", "hangar", "ghost arena", "dungeon", "exfil", "exhang", "side entrance", "maintenance",
    "cz station", "orbituary", "ruin station", "unknown", "entity"
}

# ---------------- REGEX PATTERNS ----------------
login_pattern_re = re.compile(r"\[Notice\] <Legacy login response> \[CIG-net\] User Login Success - Handle\[([A-Za-z0-9_-]+)\]", re.IGNORECASE)
version_pattern_re = re.compile(r"\[Cmdline\s*\]\s*--system-trace-env-id='pub-sc-alpha-(\d+)-\d+'", re.IGNORECASE)
player_geid_re = re.compile(r'playerGEID=(\d+)', re.IGNORECASE)
player_id_re = re.compile(r'geid (\d+).*?name ([A-Za-z0-9_-]+)', re.IGNORECASE)
spawn_reset_re = re.compile(r"<Spawn Flow>.*?Player '([^']+)' \[(\d+)\] lost reservation for spawnpoint", re.IGNORECASE)

carriage_re = re.compile(
    r'Carriage\s+(\d+)\s+\(Id:\s*([0-9]+)\)\s+for manager\s+([A-Za-z0-9_\-]+)\s+(starting|finished)\s+transit\s+in zone\s+([A-Za-z0-9_\-]+)\s+at position x:\s*([-\d.]+),\s*y:\s*([-\d.]+),\s*z:\s*([-\d.]+)',
    re.IGNORECASE
)

vehicle_destruction_re = re.compile(
    r"<Vehicle Destruction> CVehicle::OnAdvanceDestroyLevel: Vehicle '([^']+)' \[(\d+)\] in zone '([^']+)' " +
    r"\[pos x: ([-\d.]+), y: ([-\d.]+), z: ([-\d.]+) vel x: [^,]+, y: [^,]+, z: [^\]]+\] driven by '([^']+)' \[\d+\] " +
    r"advanced from destroy level (\d+) to (\d+) caused by '([^']+)' \[\d+\] with '([^']+)'",
    re.IGNORECASE
)

fuel_controller_lambda_re = re.compile(r'<lambda_1>::operator.*?Ownerless fuel controller created', re.IGNORECASE)
fuel_controller_confirm_re = re.compile(r'No vehicle for Fuel controller during RWES', re.IGNORECASE)
vehicle_control_re = re.compile(r"CVehicleMovementBase::SetDriver: Local client node \[(\d+)\] requesting control token for '([^']+)' \[(\d+)\]", re.IGNORECASE)
vehicle_granted_re = re.compile(r"CVehicle::Initialize.*?Local client node \[(\d+)\] granted control token for '([^']+)' \[(\d+)\]", re.IGNORECASE)

jump_drive_re = re.compile(r'<Jump Drive State Changed> Now (\w+).*?adam: ([^)]+)\)', re.IGNORECASE)

pos_re = re.compile(r'at position x:\s*([-\d.]+),\s*y:\s*([-\d.]+),\s*z:\s*([-\d.]+)', re.IGNORECASE)
nick_re = re.compile(r'nickname="([^"]+)"', re.IGNORECASE)
player_event_re = re.compile(r"Player:?\s+'?([^'\s,]+)'?", re.IGNORECASE)
status_re = re.compile(r"Logged a start of a status effect! nickname: ([^,]+), status effect: (.+)", re.IGNORECASE)
corpse_re = re.compile(r"Player '([^']+)'", re.IGNORECASE)
death_re = re.compile(
    r"CActor::Kill: '([^']+)' \[(\d+)\] in zone '([^']+)' killed by '([^']+)' \[(\d+)\] using '([^']+)' \[Class ([^]]+)\] with damage type '([^']+)' from direction x: ([-.\d]+), y: ([-.\d]+), z: ([-.\d]+)",
    re.IGNORECASE
)
death_alt_re = re.compile(
    r"<Actor Death>\s*CActor::Kill: '([^']+)' \[\d+\] in zone '([^']+)' killed by '([^']+)' \[[^\]]+\] using '([^']+)' \[Class ([^\]]+)\] with damage type '([^']+)'",
    re.IGNORECASE
)
death_fallback_re = re.compile(
    r"CActor::Kill: '([^']+)'(?: \[\d+\])?(?:.*?in zone '([^']+)')?(?:.*?killed by '([^']+)')?(?:.*?using '([^']+)')?(?:.*?damage type '([^']+)')?",
    re.IGNORECASE
)
incap_re = re.compile(r"Logged an incap.! nickname: ([^,]+), causes: (.+)", re.IGNORECASE)
stall_re = re.compile(r"Actor stall detected, Player: ([^,]+), Type: (\w+), Length: ([\d.]+).", re.IGNORECASE)
spawn_flow_re = re.compile(r"Player '([^']+)' \[(\d+)\].*?(?:lost|gained|reservation)", re.IGNORECASE)
entity_detach_re = re.compile(r'name = "([^"]+)".*?name = "\1"', re.IGNORECASE)
timestamp_re = re.compile(r'^<([^>]+)>')
location_re = re.compile(r'landing zone location "@([^"]+)"', re.IGNORECASE)
corpsify_re = re.compile(r"\[ActorState\] Corpse.*?Player '([^']+)'.*?Running corpsify", re.IGNORECASE)
hostility_hit_re = re.compile(
    r'Fake hit FROM\s+(\S+)\s+TO\s+(\S+)\.[^.]*?(?:Being sent to child\s+(\S+))?',
    re.IGNORECASE
)

setup_envelope_re = re.compile(
    r'<Setup Envelope Failure>.*?\|\s*([A-Z]{4}_[^[]+)\[(\d+)\]',
    re.IGNORECASE
)
spawned_re = re.compile(r'\[CSessionManager::OnClientSpawned\] Spawned!', re.IGNORECASE)
frontend_closed_re = re.compile(r'Loading screen for Frontend_Main : SC_Frontend closed after ([\d.]+) seconds', re.IGNORECASE)

# ---------------- MANAGER ALIASES ----------------
ManagerAlias = {
    "TransitManager_Hangar-to-Lobby": "HangarLobby",
    "TransitManager-001": "Elevator",
    "TransitManager_Dungeon_EntranceA": "Ghost Arena A (F2)",
    "TransitManager_Dungeon_EntranceB": "Ghost Arena B (F1)",
    "TransitManager_Dungeon_EntranceC": "Ghost Arena C (Arcade)",
    "TransitManager_Dungeon_EntranceD": "Dungeon Entrance D",
    "TransitManager_Dungeon_EntranceE": "Dungeon Entrance E",
    "TransitManager_Dungeon_EntranceF": "Dungeon Entrance F",
    "p2l4_contestedzone": "CZ Station Lobby Lifts",
    "p5l2_contestedzone": "Orbituary CZ Lobby Lifts",
    "rs_int_p6leo_ruinstation": "Ruin Station",
    "TransitManager_TransitDungeonSideEntrance": "Dungeon Side Entrance",
    "TransitManager_TransitDungeonMaintenance": "Dungeon Maintenance",
    "TransitManager_DungeonExec_RewardHangar": "EXHANG",
    "TransitManager_Dungeon_Exfil_A": "D Exfil (A)",
    "TransitManager_Dungeon_Exfil_B": "D Exfil (B)",
    "TransitManager_Dungeon_Exfil_C": "D Exfil (C)",
    "TransitManager_Dungeon_Exfil_D": "D Exfil (D)",
    "TransitManager_Dungeon_Exfil_E": "D Exfil (E)",
    "TransitManager_Dungeon_Exfil_F": "D Exfil (F)",
    "TransitManager_TransitDungeonMainEntrance": "Dungeon Entrance 04",
    "TransitManager_TransitDungeonSideEntrance": "Dungeon Entrance 02",
    "TransitManager_Habs": "Habs Transit",
}

# ---------------- SHARED STATE ----------------
state = {
    "player_pos": None,
    "entities": {},
    "events": collections.deque(maxlen=600),
    "pings": collections.defaultdict(list),
    "last_seen_player": {"name": None, "ts": 0},
    "current_station": "Station",
    "last_sound_ts": 0.0,
    "sound_enabled": False,
    "zone_mentions": collections.deque(maxlen=20),
    "transit_locations": set(),
    "detected_zones": set(),
    "player_names": set(),
    "players_killed": set(),
    "last_export": 0.0,
    "last_export_log": 0.0,
    "vehicles": {},
    "pending_vehicle": None,
    "current_vehicle": None,
    "player_name": PLAYER_NAME,
    "game_version": GAME_VERSION,
    "total_kills": 0,
    "session_kills": 0,
    "npc_kills": 0,
    "player_kills": 0,
    "session_npc_kills": 0,
    "session_player_kills": 0,
    "player_id": None,
    "spawn_reset_cooldown": {},
    "pending_server_swap": False,
    "server_swap_time": 0,
}
line_q = queue.Queue()

# ---------------- CONFIG MANAGEMENT ----------------

def load_config():
    """Load persistent configuration from file"""
    print(f"[DEBUG] Looking for export at: {EXPORT_LOG_PATH}")
    print(f"[DEBUG] Export exists: {os.path.exists(EXPORT_LOG_PATH)}")

    try:
        if os.path.exists(EXPORT_LOG_PATH):
            with open(EXPORT_LOG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
                state["npc_kills"] = config.get("npc_kills", 0)
                state["player_kills"] = config.get("player_kills", 0)
                state["total_kills"] = state["player_kills"] + state["npc_kills"]
                state["session_npc_kills"] = 0
                state["session_player_kills"] = 0
                state["session_kills"] = 0
                add_event(f"[CONFIG] Loaded {state['player_kills']} player kills, {state['npc_kills']} NPC kills (Total: {state['total_kills']})", "info")
                print(f"[DEBUG] Config loaded successfully from export")
        else:
            state["npc_kills"] = 0
            state["player_kills"] = 0
            state["total_kills"] = 0
            state["session_npc_kills"] = 0
            state["session_player_kills"] = 0
            state["session_kills"] = 0
            export_summary_to_file()
            add_event("[CONFIG] No export found, created new export file", "info")
            print(f"[DEBUG] Created new export file")
    except Exception as e:
        add_event(f"[CONFIG] Error loading config: {e}", "info")
        print(f"[DEBUG] Load error: {e}")

def scan_log_for_metadata():
    """Scan the entire game log to find player name and game version"""
    try:
        if not os.path.exists(LOG_PATH):
            return

        add_event("[SYSTEM] Scanning log file for player name and game version...", "info")

        with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if state["player_name"] == "Unknown":
                    login_m = login_pattern_re.search(line)
                    if login_m:
                        detected_name = login_m.group(1)
                        state["player_name"] = detected_name
                        global PLAYER_NAME
                        PLAYER_NAME = detected_name
                        add_event(f"[SYSTEM] Player detected: {detected_name}", "you")

                if state["player_id"] is None:
                    pid_m = player_id_re.search(line)
                    if pid_m:
                        player_id = pid_m.group(1)
                        player_name = pid_m.group(2)
                        if player_name == state.get("player_name") or state.get("player_name") == "Unknown":
                            state["player_id"] = player_id
                            add_event(f"[SYSTEM] Player ID detected: {player_id}", "info")

                    geid_m = player_geid_re.search(line)
                    if geid_m:
                        potential_geid = geid_m.group(1)
                        # Check if this line also contains our player name
                        if state.get("player_name") != "Unknown" and state["player_name"] in line:
                            state["player_id"] = potential_geid
                            add_event(f"[SYSTEM] Player GEID detected: {potential_geid}", "info")
                        elif state["player_id"] is None:
                            state["player_id"] = potential_geid

                if state["game_version"] == "Unknown":
                    version_m = version_pattern_re.search(line)
                    if version_m:
                        version_num = version_m.group(1)
                        if len(version_num) == 3:
                            detected_version = f"{version_num[0]}.{version_num[1:]}"
                        else:
                            detected_version = version_num
                        state["game_version"] = detected_version
                        global GAME_VERSION
                        GAME_VERSION = detected_version
                        add_event(f"[SYSTEM] Game version detected: {detected_version}", "info")

                if (state["player_name"] != "Unknown" and
                    state["game_version"] != "Unknown" and
                    state["player_id"] is not None):
                    break

        if state["player_name"] == "Unknown":
            add_event("[SYSTEM] Warning: Could not detect player name from log", "info")
        if state["game_version"] == "Unknown":
            add_event("[SYSTEM] Warning: Could not detect game version from log", "info")

    except Exception as e:
        add_event(f"[SYSTEM] Error scanning log: {e}", "info")

def is_self(name: str) -> bool:
    """Check if a name matches the current player (case-insensitive)"""
    if not name or not state.get("player_name"):
        return False
    return name.strip().lower() == state.get("player_name", "").strip().lower()

def clear_radar_data():
    """Clear real-time radar data when swapping servers, preserve persistent stats"""
    # Save persistent data before clearing
    persistent_kills = {
        "npc_kills": state["npc_kills"],
        "player_kills": state["player_kills"],
        "total_kills": state["total_kills"],
        "player_name": state["player_name"],
        "game_version": state["game_version"],
        "player_id": state["player_id"],
    }

    # Clear real-time tracking
    state["entities"].clear()
    state["pings"].clear()
    state["vehicles"].clear()
    state["pending_vehicle"] = None
    state["current_vehicle"] = None
    state["last_seen_player"] = {"name": None, "ts": 0}
    state["spawn_reset_cooldown"].clear()

    # Keep zone mentions but clear old ones
    state["zone_mentions"].clear()

    # Clear recent events
    state["events"].clear()

    # Reset session kills (they're for the new server session)
    state["session_npc_kills"] = 0
    state["session_player_kills"] = 0
    state["session_kills"] = 0

    # Restore persistent data
    state["npc_kills"] = persistent_kills["npc_kills"]
    state["player_kills"] = persistent_kills["player_kills"]
    state["total_kills"] = persistent_kills["total_kills"]
    state["player_name"] = persistent_kills["player_name"]
    state["game_version"] = persistent_kills["game_version"]
    state["player_id"] = persistent_kills["player_id"]

    add_event("[SERVER SWAP] Radar data cleared - new server session started", "info")
# ---------------- HELPERS ----------------
def add_event(text: str, tag: str = "info"):
    state["events"].appendleft((text, tag))

def is_valid_player_name(name: str) -> bool:
    if not name:
        return False
    n = name.strip()
    if not n:
        return False
    if n.lower() in PLAYER_NAME_BLACKLIST:
        return False
    n_lower = n.lower()
    if n_lower.startswith("team_") or n_lower.startswith("srv_"):
        return False
    if n_lower.startswith("ui_entity") or "ui_entity" in n_lower:
        return False
    if n_lower.startswith("pu_pilots") or "pu_pilots" in n_lower:
        return False
    if "human-civilian-pilot" in n_lower or "civilian_pilot" in n_lower:
        return False
    if n.isdigit() or len(n) <= 2:
        return False
    if any(ch in n for ch in "/\\@:"):
        return False
    # Check for NPC patterns with long ID numbers at the end
    if '_' in n:
        parts = n.split('_')
        # Only reject if the LAST part is a long number (10+ digits) AND there are multiple underscores
        # This allows names like "Snew_J" or "Death_Toll007" but rejects "pu_human_enemy_6392618593887"
        if len(parts) > 2 and parts[-1].isdigit() and len(parts[-1]) >= 10:
            return False
    return True

def is_npc_name(name: str) -> bool:
    if not name:
        return False
    n = name.lower()
    npc_patterns = [
        'pu_human_enemy', 'npc_', '_npc_', 'groundcombat', 'contestedzones',
        'ai_', '_ai_', 'bot_', '_bot_',
    ]
    for pattern in npc_patterns:
        if pattern in n:
            return True
    if '_' in n:
        parts = n.split('_')
        if parts[-1].isdigit() and len(parts[-1]) >= 10:
            return True
    return False

def is_vehicle_zone(zone: str) -> bool:
    z = zone.lower()
    vehicle_indicators = ['_ship_', 'container', 'vehicle', 'hull_c', 'guardian', 'misc_', 'anvl_', 'orig_', 'aegs_', 'rsi_', 'crus_', 'drak_', 'argo_', 'mrai_']
    return any(ind in z for ind in vehicle_indicators)

def normalize_manager(raw: str, zone: str = "") -> str:
    base = re.sub(r'_[0-9]+$', '', raw)
    m = re.search(r'Dungeon_Entrance_?([A-F])', base, re.IGNORECASE)
    if m:
        letter = m.group(1).upper()
        key = f"TransitManager_Dungeon_Entrance{letter}"
        return ManagerAlias.get(key, f"Dungeon Entrance {letter}")
    m2 = re.search(r'Dungeon_Exit_?([A-F])', base, re.IGNORECASE)
    if m2:
        letter = m2.group(1).upper()
        return f"Dungeon Exit {letter}"
    m3 = re.search(r'Dungeon_Exfil_?([A-F])', base, re.IGNORECASE)
    if m3:
        letter = m3.group(1).upper()
        key = f"TransitManager_Dungeon_Exfil_{letter}"
        return ManagerAlias.get(key, f"Dungeon Exfil {letter}")
    alias = ManagerAlias.get(base, base)
    alias = alias.replace("Station", state.get("current_station", "Station"))
    return alias

def classify_tag(raw_name: str) -> str:
    n = raw_name.lower()
    if 'exfil' in n or 'exit' in n:
        return 'exit'
    if 'dungeon' in n:
        return 'dungeon'
    if 'transit' in n or 'hangar' in n or 'lobby' in n:
        return 'transit'
    return 'transit'

def get_color_for_age(age: float, lifetime: float, is_newest: bool, tag: str, colors: dict) -> str:
    """Enhanced color transition - each ping fades independently based on its own age"""
    if age <= PING_FLASH_WINDOW:
        return "#ffffff"

    alpha = max(0.0, 1.0 - (age / lifetime))

    if tag == "npc_kill":
        type_col = colors['npc_kill_fg']
    elif tag == "player_kill":
        type_col = colors['player_kill_fg']
    elif tag == "dungeon":
        type_col = colors['dungeon_fg']
    elif tag == "vehicle":
        type_col = colors.get('vehicle_fg', '#00ff00')
    elif tag == "vehicle_potential":
        type_col = colors.get('vehicle_potential_fg', '#ff0000')
    elif tag == "vehicle_confirmed":
        type_col = colors.get('vehicle_confirmed_fg', '#ffff00')
    else:
        type_col = colors['transit_fg']

    if alpha >= 0.5:
        blend_factor = (1.0 - alpha) / 0.5
        return interpolate_color(type_col, "#808080", blend_factor * 0.5)
    else:
        blend_factor = (0.5 - alpha) / 0.5
        mid_color = interpolate_color(type_col, "#808080", 0.5)
        return interpolate_color(mid_color, "#505050", blend_factor)

def interpolate_color(color1: str, color2: str, ratio: float) -> str:
    c1 = tuple(int(color1[i:i+2], 16) for i in (1, 3, 5))
    c2 = tuple(int(color2[i:i+2], 16) for i in (1, 3, 5))
    result = tuple(int(c1[i] + (c2[i] - c1[i]) * ratio) for i in range(3))
    return f"#{result[0]:02x}{result[1]:02x}{result[2]:02x}"

def gray_hex_from_alpha(alpha: float) -> str:
    a = max(0.0, min(1.0, alpha))
    v = int(60 + (230 - 60) * a)
    return f"#{v:02x}{v:02x}{v:02x}"

def record_zone(zone_text: str, source: str = ""):
    if not zone_text:
        return
    zm = state.get("zone_mentions")
    if zm is None:
        return
    # Add to detected zones for export
    state["detected_zones"].add(str(zone_text))
    try:
        latest = zm[0][2]
        if isinstance(latest, str) and latest.lower() == str(zone_text).lower():
            return
    except IndexError:
        pass
    zm.appendleft((time.time(), source, str(zone_text)))

def add_ping(friendly: str, ping: dict):
    now = ping.get('ts', time.time())
    lst = state.setdefault("pings", {}).setdefault(friendly, [])
    lst.append(ping)
    state["pings"][friendly] = lst
    state["entities"][friendly] = {"pos": ping.get('pos', (0.0,0.0,0.0)), "type": ping.get('tag'), "last_seen": now}

def play_dungeon_alert():
    if not winsound:
        return
    try:
        winsound.Beep(1000, 300)
    except Exception:
        pass
    try:
        winsound.MessageBeep(getattr(winsound, 'MB_ICONEXCLAMATION', -1))
    except Exception:
        try:
            winsound.MessageBeep(-1)
        except Exception:
            pass

def export_summary_to_file():
    try:
        now_dt = datetime.now(timezone.utc)

        existing_data = {}
        if os.path.exists(EXPORT_LOG_PATH):
            try:
                with open(EXPORT_LOG_PATH, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except Exception:
                pass

        existing_transits = set(existing_data.get("unique_transits", []))
        existing_players = set(existing_data.get("unique_players", []))
        existing_players_killed = set(existing_data.get("players_killed", []))
        existing_zones = set(existing_data.get("detected_zones", []))

        current_transits = state.get("transit_locations", set())
        current_players = state.get("player_names", set())
        current_players_killed = state.get("players_killed", set())
        current_zones = state.get("detected_zones", set())

        all_transits = existing_transits.union(current_transits)
        all_players = existing_players.union(current_players)
        all_players_killed = existing_players_killed.union(current_players_killed)
        all_zones = existing_zones.union(current_zones)

        data = {
            "last_updated": now_dt.isoformat(),
            "player_name": state.get("player_name", "Unknown"),
            "game_version": state.get("game_version", "Unknown"),
            "total_kills": state.get("total_kills", 0),
            "npc_kills": state.get("npc_kills", 0),
            "player_kills": state.get("player_kills", 0),
            "unique_transits": sorted(list(all_transits)),
            "unique_players": sorted(list(all_players)),
            "players_killed": sorted(list(all_players_killed)),
            "detected_zones": sorted(list(all_zones)),
        }

        with open(EXPORT_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        current_time = time.time()
        if current_time - state.get("last_export_log", 0) > 300:
            add_event(f"[EXPORT] Data updated in {os.path.basename(EXPORT_LOG_PATH)}", "info")
            state["last_export_log"] = current_time
    except Exception as e:
        add_event(f"[EXPORT ERROR] {e}", "info")

def periodic_export_thread():
    while True:
        try:
            time.sleep(60)
            export_summary_to_file()
        except Exception:
            time.sleep(60)

# ---------------- FILE TAILER ----------------
def tail_file(path: str, out_q: queue.Queue):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(TAIL_SLEEP)
                    continue
                out_q.put(line.rstrip("\n"))
    except Exception as e:
        out_q.put(f"[ERROR] Tail thread stopped: {e}")

# ---------------- PARSER ----------------
def parser_loop(in_q: queue.Queue, state: dict):
    recent_lines = collections.deque(maxlen=400)
    while True:
        raw = in_q.get()
        if raw is None:
            time.sleep(0.05)
            continue

        if state["player_id"] is None:
            pid_m = player_id_re.search(raw)
            if pid_m:
                player_id = pid_m.group(1)
                player_name = pid_m.group(2)
                if player_name == state.get("player_name") or state.get("player_name") == "Unknown":
                    state["player_id"] = player_id
                    add_event(f"[SYSTEM] Player ID detected: {player_id}", "info")

            geid_m = player_geid_re.search(raw)
            if geid_m:
                potential_geid = geid_m.group(1)
                # Check if this line also contains our player name
                if state.get("player_name") != "Unknown" and state["player_name"] in raw:
                    state["player_id"] = potential_geid
                    add_event(f"[SYSTEM] Player GEID detected: {potential_geid}", "info")
                elif state["player_id"] is None:
                    state["player_id"] = potential_geid

        login_m = login_pattern_re.search(raw)
        if login_m:
            detected_name = login_m.group(1)
            if state["player_name"] == "Unknown" or state["player_name"] != detected_name:
                state["player_name"] = detected_name
                global PLAYER_NAME
                PLAYER_NAME = detected_name
                add_event(f"[SYSTEM] Player detected: {detected_name}", "you")

        version_m = version_pattern_re.search(raw)
        if version_m:
            version_num = version_m.group(1)
            if len(version_num) == 3:
                detected_version = f"{version_num[0]}.{version_num[1:]}"
            else:
                detected_version = version_num
            if state["game_version"] == "Unknown" or state["game_version"] != detected_version:
                state["game_version"] = detected_version
                global GAME_VERSION
                GAME_VERSION = detected_version
                add_event(f"[SYSTEM] Game version detected: {detected_version}", "info")

        ts_m = timestamp_re.search(raw)
        ts = ts_m.group(1) if ts_m else datetime.now(timezone.utc).isoformat()
        short_ts = ts.split('T')[1][:8] if 'T' in ts else ts
        recent_lines.append(raw)

        # ========== SERVER SWAP DETECTION ==========
        if spawned_re.search(raw):
            state["pending_server_swap"] = True
            state["server_swap_time"] = time.time()

        frontend_m = frontend_closed_re.search(raw)
        if frontend_m and state.get("pending_server_swap"):
            # Check if this happened within 10 seconds of the spawn
            if time.time() - state.get("server_swap_time", 0) < 10:
                load_time = frontend_m.group(1)
                add_event(f"[SERVER SWAP] Detected server change (loaded in {load_time}s) - clearing radar data", "info")
                clear_radar_data()
                state["pending_server_swap"] = False

        # ========== SPAWN RESET DETECTION ==========
        spawn_reset_m = spawn_reset_re.search(raw)
        if spawn_reset_m:
            name = spawn_reset_m.group(1).strip()
            player_id = spawn_reset_m.group(2)

            # Skip if this is your own player ID/GEID
            if player_id == state.get("player_id") or is_self(name):
                continue

            if is_valid_player_name(name):
                # Extract spawnpoint info from the full line
                spawnpoint_match = re.search(r'spawnpoint\s+([^\[]+)', raw, re.IGNORECASE)
                if spawnpoint_match:
                    spawnpoint_name = spawnpoint_match.group(1).strip()

                    # Check if this is actually a spawn reset (not just "Unknown")
                    spawn_indicators = ['bed', 'hab', 'medbay', 'medical', 'spawnpoint', 'clinic']
                    is_actual_reset = any(indicator in spawnpoint_name.lower() for indicator in spawn_indicators)

                    # Skip if it's just "Unknown" spawnpoint
                    if spawnpoint_name.lower() == "unknown":
                        continue

                    if is_actual_reset:
                        now = time.time()

                        last_reset = state["spawn_reset_cooldown"].get(name, 0)
                        if now - last_reset < 10:
                            continue

                        state["spawn_reset_cooldown"][name] = now

                        ent = state["entities"].get(name, {"type":"player", "status":"alive"})
                        ent.update({
                            "spawn_reset": True,
                            "spawn_reset_ts": now,
                            "last_seen": now
                        })
                        state["entities"][name] = ent
                        state["player_names"].add(name)
                        add_event(f"{short_ts} [SPAWN RESET] {name} reset their spawn at {spawnpoint_name}", "player")

        # ========== VEHICLE DETECTION ==========
        setup_envelope_m = setup_envelope_re.search(raw)
        if setup_envelope_m:
            vehicle_name = setup_envelope_m.group(1).strip()
            vehicle_id = setup_envelope_m.group(2).strip()
            now = time.time()

            # Store this as a pending vehicle with name
            state["pending_vehicle"] = {
                "ts": now,
                "confirmed": False,
                "name": vehicle_name,
                "id": vehicle_id,
                "from_envelope": True
            }

        if fuel_controller_lambda_re.search(raw):
            now = time.time()

            # Check if we have a pending vehicle from setup envelope (within 5 seconds)
            pending = state.get("pending_vehicle")
            if pending and pending.get("from_envelope") and (now - pending.get("ts", 0) < 5):
                # We have a named vehicle from setup envelope
                vehicle_name = pending.get("name", "Unknown Vehicle")
                vehicle_name_short = vehicle_name.split('_')[0] if '_' in vehicle_name else vehicle_name

                ping = {
                    "ts": now,
                    "pos": (0.0, 0.0, 0.0),
                    "zone": state.get("current_station", "Unknown"),
                    "action": "DETECTED",
                    "tag": "vehicle_potential",
                    "fresh": True,
                    "overlay": True,
                    "overlay_anchor": "bottom_left",
                    "vehicle_name": vehicle_name
                }
                add_ping(f"Vehicle: {vehicle_name_short}", ping)
                add_event(f"{short_ts} [VEHICLE] {vehicle_name_short} detected nearby", "vehicle")
            else:
                # Unknown vehicle
                state["pending_vehicle"] = {"ts": now, "confirmed": False}

                ping = {
                    "ts": now,
                    "pos": (0.0, 0.0, 0.0),
                    "zone": state.get("current_station", "Unknown"),
                    "action": "DETECTED",
                    "tag": "vehicle_potential",
                    "fresh": True,
                    "overlay": True,
                    "overlay_anchor": "bottom_left"
                }
                add_ping("Vehicle?", ping)

            _cleanup_pings(state)

        if fuel_controller_confirm_re.search(raw):
            if state.get("pending_vehicle") and not state["pending_vehicle"].get("confirmed"):
                state["pending_vehicle"]["confirmed"] = True
                vehicle_name = state["pending_vehicle"].get("name")

                if vehicle_name:
                    # Update named vehicle ping
                    vehicle_name_short = vehicle_name.split('_')[0] if '_' in vehicle_name else vehicle_name
                    if f"Vehicle: {vehicle_name_short}" in state["pings"]:
                        for ping in state["pings"][f"Vehicle: {vehicle_name_short}"]:
                            ping["action"] = "CONFIRMED"
                            ping["tag"] = "vehicle_confirmed"
                else:
                    # Update unknown vehicle ping
                    if "Vehicle?" in state["pings"]:
                        for ping in state["pings"]["Vehicle?"]:
                            ping["action"] = "CONFIRMED"
                            ping["tag"] = "vehicle_confirmed"

        vd_m = vehicle_destruction_re.search(raw)
        if vd_m:
            vehicle_name, vehicle_id, zone, pos_x, pos_y, pos_z, driver, level_from, level_to, caused_by, damage_type = vd_m.groups()
            now = time.time()
            pos = (float(pos_x), float(pos_y), float(pos_z))

            # Record the zone
            record_zone(zone, 'vehicle_destruction')

            if caused_by and is_valid_player_name(caused_by) and not is_self(caused_by):
                if caused_by not in state["entities"] or state["entities"].get(caused_by, {}).get("type") != "player":
                    state["entities"][caused_by] = {
                        "type": "player",
                        "status": "alive",
                        "last_seen": now,
                        "pos": pos
                    }
                    state["player_names"].add(caused_by)
                    add_event(f"{short_ts} [PLAYER] {caused_by} detected (vehicle destruction)", "player")
                else:
                    state["entities"][caused_by]["last_seen"] = now
                    state["entities"][caused_by]["pos"] = pos

            vid = vehicle_id
            state_names = {0: "Alive", 1: "Softed", 2: "FullDead"}

            if vid not in state["vehicles"]:
                state["vehicles"][vid] = {
                    "name": vehicle_name,
                    "state": int(level_from),
                    "pos": pos,
                    "zone": zone,
                    "driver": driver,
                    "last_update": now,
                    "history": []
                }

            vehicle = state["vehicles"][vid]
            vehicle["state"] = int(level_to)
            vehicle["pos"] = pos
            vehicle["zone"] = zone
            vehicle["last_update"] = now
            vehicle["history"].append({
                "from": int(level_from),
                "to": int(level_to),
                "attacker": caused_by,
                "ts": now
            })

            ping = {
                "ts": now,
                "pos": pos,
                "zone": zone,
                "action": f"{state_names[int(level_from)]}→{state_names[int(level_to)]}",
                "tag": "vehicle",
                "fresh": True,
                "vehicle_name": vehicle_name,
                "attacker": caused_by,
                "overlay": True,
                "overlay_anchor": "top_right"
            }

            friendly = f"Vehicle: {vehicle_name.split('_')[0]}"
            add_ping(friendly, ping)
            add_event(f"{short_ts} [VEHICLE {state_names[int(level_to)]}] {vehicle_name} destroyed by {caused_by} ({level_from}→{level_to})", "vehicle")
            _cleanup_pings(state)

        vc_m = vehicle_control_re.search(raw) or vehicle_granted_re.search(raw)
        if vc_m:
            client_id, vehicle_name, vehicle_id = vc_m.groups()
            state["current_vehicle"] = vehicle_name
            add_event(f"{short_ts} [MY VEHICLE] Entered {vehicle_name}", "you")

        # ========== LOCATION DETECTION ==========
        loc_m = location_re.search(raw)
        if loc_m:
            loc_raw = loc_m.group(1).lower()
            base_loc = loc_raw.replace("@pyro_", "").replace("@", "").replace("_", "")
            station_name = base_loc.title()
            record_zone(station_name, 'station')
            if station_name != state.get("current_station"):
                state["current_station"] = station_name
                add_event(f"{short_ts} [LOCATION] Detected station: {station_name}", "info")

        # ========== DOOR DETECTION ==========
        door_m = landing_door_re.search(raw)
        if door_m:
            door_name = door_m.group(1).strip()
            door_state = door_m.group(2).strip()
            now_ts = time.time()
            if 'Hangar' in door_name or 'HangarDoor' in door_name:
                friendly = normalize_manager('TransitManager_Hangar-to-Lobby')
                overlay_anchor = 'bottom_right'
            elif 'Lobby' in door_name or 'LobbyDoor' in door_name:
                friendly = normalize_manager('TransitManager-001')
                overlay_anchor = None
            else:
                friendly = door_name
                overlay_anchor = None
            ping = {
                "ts": now_ts,
                "pos": (0.0, 0.0, 0.0),
                "zone": state.get("current_station", "Station"),
                "action": door_state.upper(),
                "tag": "transit",
                "fresh": True
            }
            if overlay_anchor:
                ping["overlay"] = True
                ping["overlay_anchor"] = overlay_anchor
            add_ping(friendly, ping)
            add_event(f"{short_ts} [DOOR] {door_state} {friendly}", "transit")
            _cleanup_pings(state)

        # ========== CARRIAGE TRANSIT ==========
        m = carriage_re.search(raw)
        if m:
            car_no, car_id, manager_raw, action, zone = m.group(1,2,3,4,5)
            x, y, z = map(float, (m.group(6), m.group(7), m.group(8)))
            friendly = normalize_manager(manager_raw, zone)
            state["transit_locations"].add(friendly)
            record_zone(zone, 'transit')
            is_dungeon = bool(re.search(r'Dungeon', manager_raw, re.IGNORECASE))
            is_exfil = bool(re.search(r'Exfil', manager_raw, re.IGNORECASE) or re.search(r'Dungeon_Exfil', manager_raw, re.IGNOREIGNORE))
