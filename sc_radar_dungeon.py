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
            is_exfil = bool(re.search(r'Exfil', manager_raw, re.IGNORECASE) or re.search(r'Dungeon_Exfil', manager_raw, re.IGNORECASE))
            tag = classify_tag(manager_raw)
            action_label = "START" if "start" in action.lower() else "FINISH"
            now_ts = time.time()
            ping = {
                "ts": now_ts,
                "pos": (x, y, z),
                "zone": zone,
                "action": action_label,
                "carriage": car_no,
                "id": car_id,
                "tag": tag,
                "fresh": True
            }
            last_player = state.get("last_seen_player", {"name": None, "ts": 0})
            if last_player.get("name") and (now_ts - last_player.get("ts", 0) < PLAYER_TRANSIT_ASSOCIATION_WINDOW):
                if is_valid_player_name(last_player["name"]):
                    ping["player_name"] = last_player["name"]
                    state["last_seen_player"] = {"name": None, "ts": 0}
            if tag == 'exit':
                ping["overlay"] = True
                ping["overlay_anchor"] = "bottom_right"
            add_ping(friendly, ping)
            ping_type = "DUNGEON" if tag == 'dungeon' else "EXIT" if tag == 'exit' else "TRANSIT"
            player_part = f"[{ping['player_name']}] " if ping.get('player_name') else ""
            add_event(f"{short_ts} [{ping_type} {action_label}] {player_part}{friendly} zone={zone} pos=({x:.1f},{y:.1f},{z:.1f})", tag if tag != 'exit' else 'transit')
            if tag == 'dungeon' and state.get("sound_enabled") and (now_ts - state.get("last_sound_ts",0) > SOUND_COOLDOWN):
                play_dungeon_alert()
                state["last_sound_ts"] = now_ts
                add_event(f"{short_ts} [SOUND] Dungeon alert", "info")
            _cleanup_pings(state)
            continue

        # ========== PLAYER NICKNAMES ==========
        nm = nick_re.search(raw)
        if nm:
            name = nm.group(1).strip()
            if is_valid_player_name(name):
                # Skip if this is you
                if is_self(name):
                    continue
                
                # Check if line contains your player ID/GEID - if so, skip
                if state.get("player_id") and state["player_id"] in raw:
                    continue
                
                now = time.time()
                state["last_seen_player"] = {"name": name, "ts": now}
                    
                prevpos = None
                for prev in reversed(list(recent_lines)[-12:]):
                    pm = pos_re.search(prev)
                    if pm:
                        prevpos = tuple(map(float, pm.groups()))
                        break
                ent = state["entities"].get(name, {"type":"player", "status":"alive"})
                if prevpos:
                    ent.update({"pos": prevpos, "last_seen": now})
                    add_event(f"{short_ts} [PLAYER] {name} @ ({prevpos[0]:.1f},{prevpos[1]:.1f},{prevpos[2]:.1f})", "player")
                    if name == state["player_name"]:
                        state["player_pos"] = prevpos
                else:
                    ent.update({"last_seen": now})
                    add_event(f"{short_ts} [PLAYER] {name} detected (pos unknown)", "player")
                state["entities"][name] = ent
                state["player_names"].add(name)

        # ========== CORPSIFY DETECTION ==========
        corpsify_m = corpsify_re.search(raw)
        if corpsify_m:
            name = corpsify_m.group(1).strip()
            if is_valid_player_name(name) and not is_self(name):
                now = time.time()
                ent = state["entities"].get(name, {"type":"player","status":"alive"})
                if name not in state["entities"] or (now - ent.get("last_seen", 0) > 60):
                    ent.update({"status":"dead","last_seen":now,"death_ts":now})
                    add_event(f"{short_ts} [CORPSE INSTANT] {name} detected and immediately dead", "death")
                else:
                    ent.update({"status":"dead","last_seen":now,"death_ts":now})
                    add_event(f"{short_ts} [CORPSE] {name} is now a corpse", "death")
                state["entities"][name] = ent
                state["player_names"].add(name)

        # ========== KILL PARSING ==========
        death_m = death_re.search(raw)
        death_m_alt = None if death_m else death_alt_re.search(raw)
        killed = False
        if death_m or death_m_alt:
            if death_m:
                victim, vid, zone, killer, kid, weapon, wclass, dtype, dx, dy, dz = death_m.groups()
            else:
                victim, zone, killer, weapon, wclass, dtype = death_m_alt.groups()
            # Skip if you killed yourself
            if victim and is_self(victim):
                continue
            
            if killer and is_self(killer) and victim:
                is_npc = is_npc_name(victim)
                is_player = is_valid_player_name(victim) and not is_npc
                if is_npc or is_player:
                    now = time.time()
                    record_zone(zone, 'death')
                    
                    if is_player:
                        state["player_kills"] += 1
                        state["session_player_kills"] += 1
                        state["players_killed"].add(victim)
                    else:
                        state["npc_kills"] += 1
                        state["session_npc_kills"] += 1
                    
                    state["total_kills"] = state["player_kills"] + state["npc_kills"]
                    state["session_kills"] = state["session_player_kills"] + state["session_npc_kills"]
                    
                    if state["session_kills"] % 5 == 0 or state["session_kills"] == 1:
                        export_summary_to_file()
                    
                    prevpos = None
                    for prev in reversed(recent_lines):
                        if victim in prev:
                            p = pos_re.search(prev)
                            if p:
                                prevpos = tuple(map(float, p.groups()))
                                break
                    pos = prevpos or state.get("player_pos")
                    overlay = not prevpos and not state.get("player_pos")
                    if not pos:
                        pos = (0.0,0.0,0.0)
                    if is_player:
                        ping_tag = "player_kill"
                        friendly = "Player Kill"
                        victim_display = victim
                        add_event(f"{short_ts} [PLAYER KILL] Killed {victim_display} at pos=({pos[0]:.1f},{pos[1]:.1f},{pos[2]:.1f})", "player_kill")
                    else:
                        ping_tag = "npc_kill"
                        friendly = "NPC Kill"
                        victim_display = victim.split('_')[-2] if '_' in victim else "NPC"
                        victim_display = victim_display.capitalize()
                        add_event(f"{short_ts} [NPC KILL] Killed {victim_display}", "npc_kill")
                    
                    ping = {
                        "ts": now,
                        "pos": pos,
                        "zone": zone or "Unknown",
                        "action": "KILL",
                        "tag": ping_tag,
                        "fresh": True,
                        "overlay": overlay,
                        "victim_name": victim_display
                    }
                    if overlay:
                        ping["overlay_anchor"] = "top_right"
                    add_ping(friendly, ping)
                    state["entities"][friendly] = {"pos": pos, "type": ping_tag, "last_seen": now}
                    _cleanup_pings(state)
                    killed = True

        # ========== FALLBACK KILL ==========
        if not killed:
            fb = death_fallback_re.search(raw)
            if fb:
                victim = fb.group(1)
                zone = fb.group(2) or state.get("current_station") or "Unknown"
                killer = fb.group(3) or ""
                
                # Skip if you killed yourself
                if victim and is_self(victim):
                    continue
                
                if killer and is_self(killer) and victim:
                    is_npc = is_npc_name(victim)
                    is_player = is_valid_player_name(victim) and not is_npc
                    if is_npc or is_player:
                        now = time.time()
                        
                        if is_player:
                            state["player_kills"] += 1
                            state["session_player_kills"] += 1
                            state["players_killed"].add(victim)
                        else:
                            state["npc_kills"] += 1
                            state["session_npc_kills"] += 1
                        
                        state["total_kills"] = state["player_kills"] + state["npc_kills"]
                        state["session_kills"] = state["session_player_kills"] + state["session_npc_kills"]
                    
                        if state["session_kills"] % 5 == 0 or state["session_kills"] == 1:
                            export_summary_to_file()
                        
                        pos = None
                        for prev in reversed(recent_lines):
                            if victim in prev:
                                p = pos_re.search(prev)
                                if p:
                                    pos = tuple(map(float, p.groups()))
                                    break
                        overlay = not pos and not state.get("player_pos")
                        if is_player:
                            ping_tag = "player_kill"
                            friendly = "Player Kill"
                            victim_display = victim
                            add_event(f"{short_ts} [PLAYER KILL] Killed {victim_display} in {zone}", "player_kill")
                        else:
                            ping_tag = "npc_kill"
                            friendly = "NPC Kill"
                            victim_display = victim.split('_')[-2] if '_' in victim else "NPC"
                            victim_display = victim_display.capitalize()
                            add_event(f"{short_ts} [NPC KILL] Killed {victim_display} in {zone}", "npc_kill")
                        
                        ping = {
                            "ts": now,
                            "pos": pos or (0,0,0),
                            "zone": zone,
                            "action": "KILL",
                            "tag": ping_tag,
                            "fresh": True,
                            "overlay": overlay,
                            "victim_name": victim_display
                        }
                        if overlay:
                            ping["overlay_anchor"] = "top_right"
                        add_ping(friendly, ping)
                        state["entities"][friendly] = {"pos": pos or (0,0,0), "type": ping_tag, "last_seen": now}
                        _cleanup_pings(state)

        # ========== INCAP ==========
        incap_m = incap_re.search(raw)
        if incap_m:
            name = incap_m.group(1).strip()
            causes = incap_m.group(2).strip()
            if is_valid_player_name(name) and not is_self(name):
                now = time.time()
                ent = state["entities"].get(name, {"type":"player","status":"alive"})
                ent.update({"status":"incap","last_seen":now})
                add_event(f"{short_ts} [INCAP] {name} incapacitated, causes: {causes}", "death")
                state["entities"][name] = ent
                state["player_names"].add(name)

        # ========== CORPSE DETECTION ==========
        if "Corpse>" in raw or "corpsify" in raw.lower():
            corpse_m = corpse_re.search(raw)
            if corpse_m:
                name = corpse_m.group(1).strip()
                if is_valid_player_name(name) and not is_self(name):
                    now = time.time()
                    ent = state["entities"].get(name, {"type":"player","status":"alive"})
                    if ent.get("status") != "dead" or now - ent.get("death_ts", 0) > 10:
                        ent.update({"status":"dead","last_seen":now,"death_ts":now})
                        add_event(f"{short_ts} [CORPSE] {name} is now a corpse", "death")
                        state["entities"][name] = ent
                        state["player_names"].add(name)

        # ========== STALL ==========
        stall_m = stall_re.search(raw)
        if stall_m:
            name, stall_type, length = stall_m.groups()
            name = name.strip()
            if is_valid_player_name(name) and not is_self(name):
                now = time.time()
                if name != state["player_name"]:
                    state["last_seen_player"] = {"name": name, "ts": now}
                ent = state["entities"].get(name, {"type":"player", "status":"alive"})
                ent["last_seen"] = now
                add_event(f"{short_ts} [STALL] Saw {name} (type: {stall_type}, len: {length})", "player")
                state["entities"][name] = ent
                state["player_names"].add(name)

        # ========== PLAYER EVENTS ==========
        pem = player_event_re.search(raw)
        if pem:
            name = pem.group(1).strip()
            if is_valid_player_name(name) and not is_self(name):
                now = time.time()
                if name != state["player_name"]:
                    state["last_seen_player"] = {"name": name, "ts": now}
                ent = state["entities"].get(name, {"type":"player", "status":"alive"})
                ent["last_seen"] = now
                state["entities"][name] = ent
                state["player_names"].add(name)

        # ========== SPAWN FLOW ==========
        spawn_m = spawn_flow_re.search(raw)
        if spawn_m:
            name = spawn_m.group(1).strip()
            if is_valid_player_name(name) and not is_self(name):
                now = time.time()
                state["last_seen_player"] = {"name": name, "ts": now}
                
                ent = state["entities"].get(name, {"type":"player","status":"alive"})
                if ent.get("status") == "dead":
                    ent["status"] = "alive"
                    add_event(f"{short_ts} [SPAWN FLOW] {name} respawned, marked alive again", "player")
                else:
                    add_event(f"{short_ts} [SPAWN FLOW] Detected {name}", "player")
                
                ent["last_seen"] = now
                state["entities"][name] = ent
                state["player_names"].add(name)

        # ========== ENTITY DETACHMENT ==========
        if "CEntity::OnOwnerRemoved" in raw or "force detaching ENTITY ATTACHMENT" in raw:
            detach_m = entity_detach_re.search(raw)
            if detach_m:
                name = detach_m.group(1).strip()
                if is_valid_player_name(name) and not is_self(name):
                    now = time.time()
                    ent = state["entities"].get(name, {"type":"player", "status":"alive"})
                    ent["last_seen"] = now
                    add_event(f"{short_ts} [ENTITY] Detected {name} (entity detach)", "player")
                    state["entities"][name] = ent
                    state["player_names"].add(name)
        # ========== HOSTILITY EVENTS ==========
        hostility_m = hostility_hit_re.search(raw)
        if hostility_m:
            attacker = hostility_m.group(1).strip() if hostility_m.group(1) else None
            target = hostility_m.group(2).strip() if hostility_m.group(2) else None
            child_player = hostility_m.group(3).strip() if hostility_m.group(3) else None
            
            now = time.time()
            
            # Detect attacker if valid player
            if attacker:
                if is_valid_player_name(attacker) and not is_self(attacker):
                    state["last_seen_player"] = {"name": attacker, "ts": now}
                    
                    if attacker not in state["entities"] or state["entities"].get(attacker, {}).get("type") != "player":
                        ent = {"type": "player", "status": "alive", "last_seen": now}
                        state["entities"][attacker] = ent
                        state["player_names"].add(attacker)
                        add_event(f"{short_ts} [PLAYER] {attacker} detected (hostility attacker)", "player")
                    else:
                        state["entities"][attacker]["last_seen"] = now
            
            # Detect child player (the actual player being hit)
            if child_player:
                if is_valid_player_name(child_player) and not is_self(child_player):
                    state["last_seen_player"] = {"name": child_player, "ts": now}
                    
                    if child_player not in state["entities"] or state["entities"].get(child_player, {}).get("type") != "player":
                        ent = {"type": "player", "status": "alive", "last_seen": now}
                        state["entities"][child_player] = ent
                        state["player_names"].add(child_player)
                        add_event(f"{short_ts} [PLAYER] {child_player} detected (hostility target)", "player")
                    else:
                        state["entities"][child_player]["last_seen"] = now
        # ========== POSITION LINES ==========
        pm = pos_re.search(raw)
        if pm:
            x,y,z = map(float, pm.groups())
            assoc = None
            for prev in reversed(list(recent_lines)[-12:]):
                nm2 = nick_re.search(prev)
                if nm2:
                    assoc = nm2.group(1)
                    break
                e2 = re.search(r'(TransitManager[^\s,;:]*)', prev)
                if e2:
                    assoc = normalize_manager(e2.group(1))
                    break
            key = assoc if assoc else f"obj_{len(state['entities'])+1}"
            state["entities"][key] = {"pos": (x,y,z), "type": state["entities"].get(key,{}).get("type","transit"), "last_seen": time.time()}

        # ========== CLEANUP STALE ENTITIES ==========
        nowt = time.time()
        stale = [k for k,v in state["entities"].items() if nowt - v.get("last_seen", nowt) > ENTITY_TIMEOUT and not k in state["pings"]]
        for k in stale:
            del state["entities"][k]
        
        stale_vehicles = [vid for vid, v in state["vehicles"].items() if nowt - v.get("last_update", nowt) > VEHICLE_TIMEOUT]
        for vid in stale_vehicles:
            del state["vehicles"][vid]
        
        _cleanup_pings(state)

# ---------------- PING CLEANUP ----------------
def _cleanup_pings(state):
    """Remove expired pings and trim based on priority"""
    now = time.time()
    for key in list(state["pings"].keys()):
        pings = state["pings"][key]
        kept = []
        
        for p in pings:
            tag = str(p.get("tag", "")).lower()
            
            if "exit" in tag or "exfil" in tag:
                lifetime = EXIT_PING_LIFETIME
            elif "dungeon" in tag:
                lifetime = DUNGEON_PING_LIFETIME
            elif tag in ("npc_kill", "player_kill"):
                lifetime = NPC_KILL_LIFETIME
            elif tag == "vehicle":
                lifetime = 60.0
            elif tag in ("vehicle_potential", "vehicle_confirmed"):
                lifetime = 30.0
            else:
                lifetime = PING_LIFETIME
            
            ts = p.get("ts", 0)
            age = now - ts if ts else 999999
            
            if age <= lifetime:
                kept.append(p)
        
        kept.sort(key=lambda x: x.get("ts", 0))
        
        max_pings = 10
        
        low_priority = ["Elevator", "HangarLobby", "Habs Transit", "TransitManager-001", 
                       "TransitManager_Hangar-to-Lobby", "TransitManager_Habs", "Spaceport-to-Hangars", "Internal", "Spaceport_to_Hangars", "MetroPlatform"]
        
        if any(lp in key for lp in low_priority):
            max_pings = 1
        
        if len(kept) > max_pings:
            kept = kept[-max_pings:]
        
        for p in kept:
            p["fresh"] = False
        if kept:
            newest = kept[-1]
            newest["fresh"] = (now - newest.get("ts", 0) <= PING_FLASH_WINDOW)
        
        if kept:
            state["pings"][key] = kept
        else:
            state["pings"].pop(key, None)

# ---------------- UI ----------------
class DarkScrolledText(scrolledtext.ScrolledText):
    def __init__(self, master, colors, **kw):
        super().__init__(master, **kw)
        self.colors = colors
        self.update_colors()
    def update_colors(self):
        self.configure(bg=self.colors['log_bg'], fg=self.colors['log_fg'], insertbackground=self.colors['log_fg'], relief="flat", bd=6)

dark_colors = {
    'canvas_bg': '#000000', 'text_fg': '#e6eef6', 'grid_outline': '#1f2937',
    'player_fill': '#16a34a', 'player_outline': '#9ae6b4', 'player_glow': '#22c55e',
    'label_fg': '#ffffff', 'zoom_fg': '#94a3b8', 'panel_bg': '#0a111a',
    'log_bg': '#0b0f12', 'log_fg': '#e6eef6', 'legend_fg': '#cbd5e1',
    'dungeon_fg': '#ff7bff', 'transit_fg': '#6ff0ff', 'player_fg': '#ffd86b',
    'you_fg': '#7dff9e', 'info_fg': '#d9e6ef', 'death_fg': '#ff0000',
    'alive_fg': '#00ff00', 'dead_fg': '#ff0000', 'incap_fg': '#ffa500',
    'faded_fg': '#90ee90', 'gray_fg': '#a9a9a9', 'line_fill': '#4a5568',
    'npc_kill_fg': '#ffa500', 'player_kill_fg': '#ff4500', 'vehicle_fg': '#00ff00', 'vehicle_destroy_fg': '#ff6600',
    'vehicle_potential_fg': '#ff0000', 'vehicle_confirmed_fg': '#ffff00'
}

light_colors = {
    'canvas_bg': '#ffffff', 'text_fg': '#000000', 'grid_outline': '#d3d3d3',
    'player_fill': '#228b22', 'player_outline': '#006400', 'player_glow': '#32cd32',
    'label_fg': '#000000', 'zoom_fg': '#696969', 'panel_bg': '#f0f0f0',
    'log_bg': '#f5f5f5', 'log_fg': '#000000', 'legend_fg': '#4b4b4b',
    'dungeon_fg': '#c71585', 'transit_fg': '#00bfff', 'player_fg': '#b8860b',
    'you_fg': '#008000', 'info_fg': '#4b4b4b', 'death_fg': '#ff0000',
    'alive_fg': '#008000', 'dead_fg': '#ff0000', 'incap_fg': '#ff8c00',
    'faded_fg': '#90ee90', 'gray_fg': '#a9a9a9', 'line_fill': '#a9a9a9',
    'npc_kill_fg': '#ff8c00', 'player_kill_fg': '#d2691e', 'vehicle_fg': '#006400', 'vehicle_destroy_fg': '#ff4500',
    'vehicle_potential_fg': '#cc0000', 'vehicle_confirmed_fg': '#cccc00'
}
class RadarApp:
    def __init__(self, root, state):
        self.root = root
        self.state = state
        self.W = 820
        self.H = 720
        self.scale = INITIAL_SCALE
        self.label_font = font.Font(family="TkDefaultFont", size=10)
        self.dark_mode = tk.BooleanVar(value=True)
        self.sound_alert = tk.BooleanVar(value=False)
        self.colors = dark_colors if self.dark_mode.get() else light_colors

        menubar = tk.Menu(root)
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(label="Dark Mode", variable=self.dark_mode, command=self.toggle_mode)
        view_menu.add_checkbutton(label="Dungeon Sound Alert", variable=self.sound_alert)
        menubar.add_cascade(label="Options", menu=view_menu)
        root.config(menu=menubar)

        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except Exception:
            pass
        self.update_style()
        root.configure(bg=self.colors['panel_bg'])

        self.canvas = tk.Canvas(root, width=self.W, height=self.H, bg=self.colors['canvas_bg'],
                                highlightthickness=0, bd=2, relief="ridge")
        self.canvas.grid(row=1, column=0, rowspan=3, padx=(8,4), pady=8, sticky="nsew")
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)
        self.canvas.bind("<Configure>", self.on_canvas_resize)

        self.panel = ttk.Frame(root, style="Dark.TFrame")
        self.panel.grid(row=1, column=1, sticky="nsew", padx=(4,8), pady=8)

        root.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(1, weight=0, minsize=400)
        root.grid_rowconfigure(0, weight=0)
        root.grid_rowconfigure(1, weight=1)
        root.grid_rowconfigure(2, weight=0)
        root.grid_rowconfigure(3, weight=0)

        self.panel.grid_rowconfigure(1, weight=1)
        self.panel.grid_rowconfigure(4, weight=1)
        self.panel.grid_rowconfigure(6, weight=1)
        self.panel.grid_columnconfigure(0, weight=1)

        self.title_label = ttk.Label(root, text="Yertz Advanced Personal Reporter",
                                     style="Header.TLabel")
        self.title_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(8,4))

        ttk.Label(self.panel, text="Recent Events (Newest First)",
                 style="Header.TLabel").grid(row=0, column=0, sticky="w", pady=(4,0))
        self.log = DarkScrolledText(self.panel, self.colors, width=60, height=12,
                                   wrap="word", font=("TkDefaultFont",10))
        self.log.grid(row=1, column=0, sticky="nsew", pady=(6,6))
        self.log.configure(state="normal")
        self.update_log_tags()

        self.legend = ttk.Label(self.panel,
                               text="Green=You  Yellow=Player  Cyan=Transit  Magenta=Dungeon  Orange=NPC Kill  OrangeRed=Player Kill  LimeGreen=Vehicle  White=New",
                               style="Legend.TLabel")
        self.legend.grid(row=2, column=0, sticky="w", pady=(4,0))

        ttk.Label(self.panel, text="Detected Players",
                 style="Header.TLabel").grid(row=3, column=0, sticky="w", pady=(8,0))
        
        kill_frame = ttk.Frame(self.panel, style="Dark.TFrame")
        kill_frame.grid(row=3, column=0, sticky="e", pady=(8,0))
        self.kill_label = ttk.Label(kill_frame, text="Kills: 0", style="Legend.TLabel", 
                                    font=("TkDefaultFont", 10, "bold"))
        self.kill_label.pack()
        
        self.players_log = DarkScrolledText(self.panel, self.colors, width=60, height=10,
                                           wrap="word", font=("TkDefaultFont",10))
        self.players_log.grid(row=4, column=0, sticky="nsew", pady=(6,6))
        self.players_log.configure(state="normal")
        self.update_players_tags()

        ttk.Label(self.panel, text="Nearby Vehicles",
                 style="Header.TLabel").grid(row=5, column=0, sticky="w", pady=(8,0))
        self.vehicles_log = DarkScrolledText(self.panel, self.colors, width=60, height=8,
                                            wrap="word", font=("TkDefaultFont",10))
        self.vehicles_log.grid(row=6, column=0, sticky="nsew", pady=(6,6))
        self.vehicles_log.configure(state="normal")
        self.update_vehicles_tags()

        self.running = True
        self.refresh()

    def on_canvas_resize(self, event):
        self.W = event.width
        self.H = event.height

    def toggle_mode(self):
        self.colors = dark_colors if self.dark_mode.get() else light_colors
        self.root.configure(bg=self.colors['panel_bg'])
        self.canvas.configure(bg=self.colors['canvas_bg'])
        self.update_style()
        self.log.update_colors()
        self.players_log.update_colors()
        self.vehicles_log.update_colors()
        self.update_log_tags()
        self.update_players_tags()
        self.update_vehicles_tags()

    def update_style(self):
        self.style.configure("Dark.TFrame", background=self.colors['panel_bg'],
                           borderwidth=1, relief="solid")
        self.style.configure("TLabel", background=self.colors['panel_bg'],
                           foreground=self.colors['text_fg'])
        self.style.configure("Header.TLabel", font=("TkDefaultFont",12,"bold"),
                           foreground=self.colors['label_fg'])
        self.style.configure("Legend.TLabel", font=("TkDefaultFont",10),
                           foreground=self.colors['legend_fg'])

    def update_log_tags(self):
        self.log.tag_config('dungeon', foreground=self.colors['dungeon_fg'],
                           font=("TkDefaultFont",10,"bold"))
        self.log.tag_config('transit', foreground=self.colors['transit_fg'],
                           font=("TkDefaultFont",10,"bold"))
        self.log.tag_config('player', foreground=self.colors['player_fg'],
                           font=("TkDefaultFont",10,"bold"))
        self.log.tag_config('you', foreground=self.colors['you_fg'],
                           font=("TkDefaultFont",10,"bold"))
        self.log.tag_config('info', foreground=self.colors['info_fg'])
        self.log.tag_config('death', foreground=self.colors['death_fg'],
                           font=("TkDefaultFont",10,"bold"))
        self.log.tag_config('npc_kill', foreground=self.colors['npc_kill_fg'],
                           font=("TkDefaultFont",10,"bold"))
        self.log.tag_config('player_kill', foreground=self.colors['player_kill_fg'],
                           font=("TkDefaultFont",10,"bold"))
        self.log.tag_config('vehicle', foreground=self.colors['vehicle_fg'],
                           font=("TkDefaultFont",10,"bold"))

    def update_players_tags(self):
        self.players_log.tag_config('alive', foreground=self.colors['alive_fg'])
        self.players_log.tag_config('dead', foreground=self.colors['dead_fg'])
        self.players_log.tag_config('incap', foreground=self.colors['incap_fg'])
        self.players_log.tag_config('faded', foreground=self.colors['faded_fg'])
        self.players_log.tag_config('gray', foreground=self.colors['gray_fg'])

    def update_vehicles_tags(self):
        self.vehicles_log.tag_config('alive', foreground=self.colors['vehicle_fg'])
        self.vehicles_log.tag_config('softed', foreground=self.colors['incap_fg'])
        self.vehicles_log.tag_config('dead', foreground=self.colors['vehicle_destroy_fg'])

    def on_mousewheel(self, event):
        if hasattr(event, "delta"):
            self.scale *= 1.12 if event.delta > 0 else 0.88
        else:
            self.scale *= 1.12 if event.num == 4 else 0.88
        self.scale = max(0.2, min(40.0, self.scale))

    def world_to_screen(self, dx, dy):
        return self.W/2 + dx * self.scale, self.H/2 - dy * self.scale

    def draw(self):
        self.canvas.delete("all")
        now = time.time()

        for r in (25, 50, 100, 250, 500):
            self.canvas.create_oval(self.W/2 - r*self.scale, self.H/2 - r*self.scale,
                                   self.W/2 + r*self.scale, self.H/2 + r*self.scale,
                                   outline=self.colors['grid_outline'], width=1)

        self.canvas.create_oval(self.W/2-PLAYER_DOT_RADIUS, self.H/2-PLAYER_DOT_RADIUS,
                               self.W/2+PLAYER_DOT_RADIUS, self.H/2+PLAYER_DOT_RADIUS,
                               fill=self.colors['player_fill'],
                               outline=self.colors['player_outline'], width=2)
        self.canvas.create_oval(self.W/2-PLAYER_DOT_RADIUS_INNER, self.H/2-PLAYER_DOT_RADIUS_INNER,
                               self.W/2+PLAYER_DOT_RADIUS_INNER, self.H/2+PLAYER_DOT_RADIUS_INNER,
                               fill=self.colors['player_glow'],
                               outline=self.colors['player_outline'])

        self.canvas.create_text(12, 10, anchor="nw", text=f"You: {self.state.get('player_name', 'Unknown')}",
                               fill=self.colors['label_fg'], font=("TkDefaultFont",11,"bold"))
        
        current_vehicle = self.state.get("current_vehicle")
        if current_vehicle:
            vehicle_display = current_vehicle.split('_')[0] if '_' in current_vehicle else current_vehicle
            self.canvas.create_text(12, 28, anchor="nw", text=f"Vehicle: {vehicle_display}",
                                   fill=self.colors['vehicle_fg'], font=("TkDefaultFont",10,"bold"))
            y_offset = 48
        else:
            y_offset = 30
        
        self.canvas.create_text(12, y_offset, anchor="nw", text=f"Zoom: {self.scale:.2f}x",
                               fill=self.colors['zoom_fg'], font=("TkDefaultFont",10))

        y = y_offset + 18
        mentions = list(self.state.get("zone_mentions", []))[:MAX_ZONE_MENTIONS_DISPLAY]
        for ts, src, ztxt in reversed(mentions):
            label = f"{src}: {ztxt}" if src else str(ztxt)
            self.canvas.create_text(12, y, anchor="nw", text=label,
                                   fill=self.colors['label_fg'], font=("TkDefaultFont",9))
            y += 16

        placed_label_boxes = []
        all_pings = []
        for manager, ping_list in self.state["pings"].items():
            for idx, ping in enumerate(ping_list):
                all_pings.append({'manager': manager, 'ping': ping, 'idx': idx})

        player_pos = self.state.get("player_pos") or (0.0, 0.0, 0.0)
        all_pings.sort(key=lambda item: self.world_to_screen(
            item['ping'].get('pos', (0,0,0))[0] - player_pos[0],
            item['ping'].get('pos', (0,0,0))[1] - player_pos[1])[1])

        overlay_top_row = 0
        overlay_bottom_row = 0
        overlay_bottom_left_row = 0
        for item in all_pings:
            manager, ping, idx = item['manager'], item['ping'], item['idx']
            is_newest = (idx == len(self.state["pings"][manager]) - 1)
            age = now - ping["ts"]
            lifetime = (DUNGEON_PING_LIFETIME if ping.get('tag') == 'dungeon'
                       else NPC_KILL_LIFETIME if ping.get('tag') in ('npc_kill','player_kill')
                       else (60.0 if ping.get('tag') == 'vehicle'
                            else (30.0 if ping.get('tag') in ('vehicle_potential', 'vehicle_confirmed')
                                 else (EXIT_PING_LIFETIME if ping.get('tag') == 'exit' else PING_LIFETIME))))
            if age > lifetime or not ping.get("pos"):
                continue

            is_overlay = bool(ping.get('overlay'))

            if is_overlay:
                margin = 12
                anchor = ping.get('overlay_anchor', 'top_right')
                if anchor == 'top_right':
                    sx = self.W - margin
                    sy = 48 + overlay_top_row * STACK_OFFSET_PX
                    overlay_top_row += 1
                elif anchor == 'bottom_right':
                    sx = self.W - margin
                    sy = self.H - (48 + overlay_bottom_row * STACK_OFFSET_PX)
                    overlay_bottom_row += 1
                elif anchor == 'bottom_left':
                    sx = margin
                    sy = self.H - (48 + overlay_bottom_left_row * STACK_OFFSET_PX)
                    overlay_bottom_left_row += 1
                else:
                    sx = self.W - margin
                    sy = 48 + overlay_top_row * STACK_OFFSET_PX
                    overlay_top_row += 1
            else:
                dx, dy = ping["pos"][0] - player_pos[0], ping["pos"][1] - player_pos[1]
                sx, sy = self.world_to_screen(dx, dy)

            color = get_color_for_age(age, lifetime, is_newest, ping["tag"], self.colors)

            player_name_str = f"{ping['player_name']} | " if ping.get("player_name") else ""
            victim_name_str = f"{ping.get('victim_name', '')} | " if ping.get("victim_name") else ""
            vehicle_name_str = f"{ping.get('vehicle_name', '').split('_')[0]} | " if ping.get("vehicle_name") else ""
            attacker_str = f"by {ping.get('attacker', '')} | " if ping.get("attacker") else ""
            
            display_name = re.sub(r'TransitManager[-_]?','', manager).strip()
            display_name = display_name if len(display_name) <= 30 else (display_name[:27] + "...")

            age_str = f"({int(age)}s ago)"
            label = f"{player_name_str}{victim_name_str}{vehicle_name_str}{attacker_str}{display_name} | {ping['action']} | {age_str}"

            lbl_col = self.colors['player_fg'] if ping.get("player_name") else color

            label_width = self.label_font.measure(label)
            label_height = self.label_font.metrics("linespace")

            if is_overlay:
                if ping.get('overlay_anchor') == 'bottom_left':
                    label_sx_start = sx
                    text_anchor = "w"
                else:
                    label_sx_start = sx - label_width
                    text_anchor = "w"
            else:
                label_sx_start = sx + 12
                text_anchor = "w"

            final_label_sy = sy
            for _ in range(10):
                current_box = (label_sx_start, final_label_sy - label_height/2,
                              label_sx_start + label_width, final_label_sy + label_height/2)
                overlap = False
                for pb in placed_label_boxes:
                    if not (current_box[2] < pb[0] or current_box[0] > pb[2] or
                           current_box[3] < pb[1] or current_box[1] > pb[3]):
                        overlap = True
                        break
                if not overlap:
                    break
                final_label_sy += label_height * 0.6

            placed_label_boxes.append((label_sx_start, final_label_sy - label_height/2,
                                      label_sx_start + label_width, final_label_sy + label_height/2))

            r = 8 if is_newest else 6
            outline_col = "#ffffff"
            
            is_kill = ping["tag"] in ("npc_kill", "player_kill", "vehicle")
            
            if is_kill:
                self.canvas.create_rectangle(sx-r-1, sy-r-1, sx+r+1, sy+r+1,
                                           fill=color, outline=outline_col, width=1)
                self.canvas.create_rectangle(sx-r, sy-r, sx+r, sy+r,
                                           fill=color, outline=self.colors['canvas_bg'])
            else:
                self.canvas.create_oval(sx-r-1, sy-r-1, sx+r+1, sy+r+1,
                                       fill=color, outline=outline_col, width=1)
                self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r,
                                       fill=color, outline=self.colors['canvas_bg'])

            self.canvas.create_text(label_sx_start, final_label_sy, anchor=text_anchor,
                                   text=label, fill=lbl_col, font=self.label_font)

            if abs(final_label_sy - sy) > 1:
                if ping.get('overlay_anchor') == 'bottom_left':
                    line_start_x = sx + r
                    line_end_x = label_sx_start - 3
                elif is_overlay:
                    line_start_x = sx - r
                    line_end_x = label_sx_start - 3
                else:
                    line_start_x = sx + r
                    line_end_x = label_sx_start - 3
                self.canvas.create_line(line_start_x, sy, line_end_x, final_label_sy,
                                       fill=self.colors['line_fill'], dash=(2,2))

        for name, ent in list(self.state["entities"].items()):
            if not ent.get("pos") or name in self.state["pings"] or name == PLAYER_NAME:
                continue
            dx, dy = ent["pos"][0] - player_pos[0], ent["pos"][1] - player_pos[1]
            sx, sy = self.world_to_screen(dx, dy)

            col = (self.colors['player_fg'] if ent.get("type")=="player"
                  else self.colors['transit_fg'])
            self.canvas.create_oval(sx-6, sy-6, sx+6, sy+6,
                                   fill=col, outline="#ffffff", width=1)
            self.canvas.create_text(sx+10, sy, anchor="w", text=name,
                                   fill=self.colors['label_fg'], font=self.label_font)

    def update_log(self):
        self.log.delete("1.0", tk.END)
        for text, tag in list(self.state["events"]):
            try:
                self.log.insert(tk.END, text + "\n", tag)
            except Exception:
                self.log.insert(tk.END, text + "\n")
            self.log.insert(tk.END, "-"*80 + "\n", "info")
        self.log.yview_moveto(0.0)

    def update_players(self):
        self.players_log.delete("1.0", tk.END)
        now = time.time()
        players = [(v["last_seen"], k, v) for k, v in self.state["entities"].items()
                  if v.get("type") == "player" and k != self.state.get("player_name", "Unknown") and is_valid_player_name(k)]
        players.sort(reverse=True)

        for last, name, ent in players:
            age = int(now - last)
            status_parts = []
            
            if ent.get("spawn_reset") and (now - ent.get("spawn_reset_ts", 0) < 300):
                status_parts.append("Reset Spawn")
            
            if ent.get("status") == "dead":
                death_age = int(now - ent.get("death_ts", now))
                status_parts.append(f"dead for {death_age}s")
                tag = 'dead'
            elif ent.get("status") == "incap":
                status_parts.append("incap")
                tag = 'incap'
            else:
                tag = 'alive' if age < 180 else 'faded' if age < 300 else 'gray'
            
            if ent.get("spawn_reset") and (now - ent.get("spawn_reset_ts", 0) < 300):
                tag = 'faded'
            
            status_parts.append(f"seen {age}s ago")
            
            status_str = ", ".join(status_parts)
            text = f"{name} ({status_str})\n"
            
            self.players_log.insert(tk.END, text, tag)

        self.players_log.yview_moveto(0.0)

    def update_vehicles(self):
        self.vehicles_log.delete("1.0", tk.END)
        now = time.time()
        
        if self.state.get("pending_vehicle"):
            pv = self.state["pending_vehicle"]
            age = int(now - pv.get("ts", now))
            status = "CONFIRMED" if pv.get("confirmed") else "POTENTIAL"
            text = f"Vehicle? - {status} - {age}s ago\n"
            tag = 'softed' if pv.get("confirmed") else 'dead'
            self.vehicles_log.insert(tk.END, text, tag)
        
        if not self.state.get("vehicles") and not self.state.get("pending_vehicle"):
            self.vehicles_log.insert(tk.END, "No vehicles detected\n", "gray")
            return
        
        vehicles = sorted(self.state["vehicles"].items(), 
                         key=lambda x: x[1].get("last_update", 0), reverse=True)
        
        for vid, vehicle in vehicles:
            age = int(now - vehicle.get("last_update", now))
            state_names = {0: "Alive", 1: "Softed", 2: "FullDead"}
            state_name = state_names.get(vehicle.get("state", 0), "Unknown")
            
            if vehicle.get("state") == 2:
                tag = 'dead'
            elif vehicle.get("state") == 1:
                tag = 'softed'
            else:
                tag = 'alive'
            
            vname = vehicle.get("name", "Unknown")
            vname_short = vname.split('_')[0] if '_' in vname else vname
            
            text = f"{vname_short} - {state_name}"
            
            if vehicle.get("history"):
                latest = vehicle["history"][-1]
                attacker = latest.get("attacker", "Unknown")
                if attacker and attacker != "unknown":
                    text += f" (by {attacker})"
            
            text += f" - {age}s ago\n"
            
            self.vehicles_log.insert(tk.END, text, tag)
        
        self.vehicles_log.yview_moveto(0.0)

    def refresh(self):
        if not self.running:
            return
        self.state["sound_enabled"] = self.sound_alert.get()
        
        version = self.state.get("game_version", "Unknown")
        if version != "Unknown":
            self.root.title(f"Yertz Advanced Personal Reporter - v{version}")
        else:
            self.root.title("Yertz Advanced Personal Reporter")
        
        total_kills = self.state.get("total_kills", 0)
        session_kills = self.state.get("session_kills", 0)
        player_kills = self.state.get("player_kills", 0)
        npc_kills = self.state.get("npc_kills", 0)
        session_player_kills = self.state.get("session_player_kills", 0)
        session_npc_kills = self.state.get("session_npc_kills", 0)
        
        kill_text = f"Player: {player_kills} ({session_player_kills}) | NPC: {npc_kills} ({session_npc_kills})"
        self.kill_label.configure(text=kill_text)
        
        try:
            self.draw()
            self.update_log()
            self.update_players()
            self.update_vehicles()
        except Exception as e:
            print("UI update error:", e)
        self.root.after(300, self.refresh)

# ---------------- MAIN ----------------
def main():
    if not os.path.exists(LOG_PATH):
        root = tk.Tk()
        root.withdraw()
        from tkinter import messagebox
        messagebox.showerror(
            "Game.log Not Found",
            f"Game.log not found at:\n{LOG_PATH}\n\n"
            "Please start Star Citizen to generate the Game.log file."
        )
        root.destroy()
        return

    load_config()
    
    scan_thread = threading.Thread(target=scan_log_for_metadata, daemon=True)
    scan_thread.start()

    threading.Thread(target=tail_file, args=(LOG_PATH, line_q), daemon=True).start()
    threading.Thread(target=parser_loop, args=(line_q, state), daemon=True).start()
    threading.Thread(target=periodic_export_thread, daemon=True).start()

    root = tk.Tk()
    root.title("Yertz Advanced Personal Reporter")
    app = RadarApp(root, state)
    
    def on_close():
        try:
            export_summary_to_file()
        except Exception as e:
            print(f"Error saving on close: {e}")
        finally:
            os._exit(0)
    
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == "__main__":
    main()