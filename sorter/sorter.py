#!/usr/bin/env python3
"""
Ashes of Creation PCAP Organizer

Sorts PCAP files into organized folders based on:
  1. File header metadata (Capture Target, Player Class)
  2. Filename keyword analysis
  3. Positional first-word fallback

Usage:
  python sorter.py [--dry-run] [--reorganize]
"""

import argparse
import os
import re
import shutil
from pathlib import Path
from typing import List, Optional


# ============================================================================
# CONSTANTS
# ============================================================================

ARCHETYPES = {
    'tank', 'fighter', 'rogue', 'ranger',
    'mage', 'summoner', 'cleric', 'bard', 'archer',
}

CLASSES = {
    'guardian', 'knight', 'nightshield', 'sentinel', 'spellshield', 'brood_warden',
    'weapon_master', 'dreadnought', 'shadowblade', 'hunter', 'spellsword', 'bladecaller',
    'duelist', 'shadowguard', 'assassin', 'predator', 'nightspell', 'shadow_lord',
    'strider', 'soulbow', 'scout', 'hawkeye', 'scion', 'beastmaster',
    'archwizard', 'spellstone', 'shadow_caster', 'spellhunter', 'arcanist', 'warlock',
    'conjurer', 'shadowmancer', 'spellmancer', 'wild_blade', 'necromancer', 'enchanter',
    'apostle', 'templar', 'shadow_disciple', 'protector', 'oracle', 'shaman', 'high_priest',
    'minstrel', 'tellsword', 'trickster', 'bowsinger', 'magician', 'songcaller', 'soul_weaver',
}

ALL_CLASS_NAMES = ARCHETYPES | CLASSES

# Prefixes used in aoc_<prefix>_<topic> that should be treated like class names
# (i.e., the class part is WHO captured, not WHAT was captured)
AOC_TOPIC_PREFIXES = ALL_CLASS_NAMES | {
    'character', 'action', 'inventory', 'weapon',
}

STOP_WORDS = {
    'aoc', 'pcap', 'pcapng', 'cap', 'capture', 'file', 'data', 'test',
    'final', 'finale', 'perfect', 'good', 'best', 'fixed', 'clean',
    'copy', 'old', 'hexdump', 'the', 'and', 'for', 'with', 'from',
    'into', 'then', 'all', 'after', 'before', 'not', 'yet', 'done',
    'ashes', 'creation', 'packet', 'value', 'value2', 'value5', 'value6',
}

# Known materials/resources in the game
MATERIALS = {
    'basalt', 'granite', 'iron', 'obsidian', 'sandstone', 'slate',
    'volcanic', 'volcanicrock', 'zinc', 'copper', 'tendonite', 'resonite',
    'saelacith', 'rough', 'roughseaglass', 'coveglass', 'deadcoral',
    'bagkindo', 'roughrime', 'tin',
}

# Known crafting stations / NPC shop types
CRAFTING_STATIONS = {
    'smithy', 'stoneworks', 'laboratory', 'cookhouse', 'lumbermill',
    'tannery', 'weaver', 'kiln', 'smelter',
}

# ============================================================================
# CAPTURE TARGET -> FOLDER RULES  (checked in order, first match wins)
# ============================================================================

CAPTURE_TARGET_RULES = [
    # Combat
    (r'combat\s*[-:]\s*ability\s*rotation', ['combat_pve']),
    (r'combat\s*[-:]\s*basic\s*attack', ['combat_pve']),
    (r'combat\s*[-:]\s*pvp', ['combat_pvp']),
    (r'combat\s*[-:]\s*pve', ['combat_pve']),
    (r'combat\s*[-:]', ['combat_pve']),

    # World systems
    (r'world\s*[-:]\s*sports?\s*fishing', ['world_gathering', 'sport_fishing']),
    (r'world\s*[-:]\s*processing', ['world_processing']),
    (r'world\s*[-:]\s*gathering', ['world_gathering']),
    (r'world\s*[-:]\s*npc\s*interaction', ['world_npc_interaction']),

    # Movement
    (r'movement\s*[-:]\s*mounts?', ['mounts']),
    (r'movement\s*[-:]\s*swimming', ['generic', 'movement', 'swimming']),
    (r'movement\s*[-:]\s*climbing', ['generic', 'movement']),
    (r'movement\s*[-:]', ['generic', 'movement']),

    # Mayor / Node
    (r'mayor', ['nodes']),
    (r'\bnode\b', ['nodes']),

    # Mounts
    (r'mount\s+summon', ['mounts']),
    (r'mount\s+dismiss', ['mounts']),
    (r'mount\s+mounting', ['mounts']),
    (r'mount\s+unmounting', ['mounts']),
    (r'mount\s+flourish', ['mounts']),
    (r'\bmount\b', ['mounts']),
    (r'\bflying\b', ['mounts']),
    (r'despawning.mount', ['mounts']),
    (r'spawning.mount', ['mounts']),
    (r'running\s+across\s+sw', ['server_workers']),

    # Economy / Marketplace
    (r'marketplace', ['economy']),
    (r'creating.buy.order', ['economy']),
    (r'buy\s*order', ['economy']),
    (r'talking.to.vendor', ['economy']),
    (r'\bvendor\b', ['economy']),
    (r'\btrading\b', ['social_trading']),

    # Social
    (r'add.friend', ['friend_management']),
    (r'invite.friend', ['social_communication']),
    (r'invite.*party', ['social_communication']),
    (r'promote.*party', ['social_communication']),
    (r'talking.*guild.*chat', ['social_communication']),
    (r'talking.*party.*chat', ['social_communication']),
    (r'being.*invited.*guild', ['guild_management']),
    (r'leaving.*guild', ['guild_management']),
    (r'\bguild\b', ['social']),
    (r'\bparty\b', ['social']),
    (r'\bfriend\b', ['social']),
    (r'\bchat\b', ['social_communication']),
]

# ============================================================================
# FILENAME -> FOLDER RULES  (checked in order, first match wins)
# Each: (lambda(normalized_filename, word_set) -> bool, folder_parts)
#
# ORDERING IS CRITICAL: system-level rules FIRST, then fallback catches.
# ============================================================================

def _has_any(w, *words):
    """Helper: check if word set contains any of the given words."""
    return bool(w & set(words))


FILENAME_RULES = [
    # =====================================================================
    # 1. PROCESSING (highest priority — before anything else)
    # =====================================================================
    (lambda fn, w: 'processing' in w, ['world_processing']),
    (lambda fn, w: fn.startswith('processing_'), ['world_processing']),
    (lambda fn, w: '_sand_processing' in fn, ['world_processing']),
    (lambda fn, w: '_fragment_craft' in fn, ['world_processing']),
    (lambda fn, w: '_powder_craft' in fn, ['world_processing']),
    (lambda fn, w: '_ashlarblock' in fn or 'ashlarblock' in w, ['world_processing']),
    (lambda fn, w: 'stonemason' in w, ['world_processing']),
    (lambda fn, w: 'metalworking' in w, ['world_processing']),

    # =====================================================================
    # 2. CLAIM (resource/node claims → world_processing)
    # =====================================================================
    (lambda fn, w: 'claim' in w and _has_any(w, *MATERIALS), ['world_processing']),
    (lambda fn, w: '_sand_claim' in fn, ['world_processing']),
    (lambda fn, w: '_fragment_claim' in fn, ['world_processing']),

    # =====================================================================
    # 3. GATHERING
    # =====================================================================
    (lambda fn, w: 'gathering' in w, ['world_gathering']),
    (lambda fn, w: fn.startswith('gather_'), ['world_gathering']),
    (lambda fn, w: fn.startswith('gathering_'), ['world_gathering']),
    (lambda fn, w: 'harvest' in w and 'tree' in w, ['world_gathering']),
    (lambda fn, w: 'chopping' in w, ['world_gathering']),
    (lambda fn, w: 'coconut' in w and 'tree' in w, ['world_gathering']),

    # =====================================================================
    # 4. FISHING
    # =====================================================================
    (lambda fn, w: 'sportfishing' in fn or 'sportsfishing' in fn or 'sports_fishing' in fn, ['world_gathering', 'sport_fishing']),
    (lambda fn, w: 'sport' in w and 'fishing' in w, ['world_gathering', 'sport_fishing']),
    (lambda fn, w: 'fish' in w and _has_any(w, 'crate', 'crates', 'selling', 'storing'), ['world_gathering', 'sport_fishing']),
    (lambda fn, w: 'fishing' in w, ['world_gathering', 'fishing']),
    (lambda fn, w: fn.startswith('aocfishing'), ['world_gathering', 'fishing']),
    (lambda fn, w: 'fish' in w and 'escaping' in w, ['world_gathering', 'fishing']),

    # =====================================================================
    # 5. CARAVANS / TRANSPORT
    # =====================================================================
    (lambda fn, w: _has_any(w, 'caravan', 'carvan', 'caravans'), ['transport_caravans']),
    (lambda fn, w: 'corsair' in w, ['transport_caravels']),
    (lambda fn, w: _has_any(w, 'crate', 'crates') and _has_any(w, 'craft', 'construction'), ['transport_crates']),
    (lambda fn, w: _has_any(w, 'crate', 'crates') and _has_any(w, 'storage', 'warehouse'), ['transport_crates']),
    (lambda fn, w: _has_any(w, 'crate', 'crates') and _has_any(w, 'drop', 'pick', 'pickup'), ['transport_crates']),
    (lambda fn, w: _has_any(w, 'crate', 'crates') and _has_any(w, 'equip', 'unequip'), ['transport_crates']),
    (lambda fn, w: _has_any(w, 'crate', 'crates') and _has_any(w, 'buying', 'certificate', 'certificates'), ['transport_crates']),
    (lambda fn, w: _has_any(w, 'crate', 'crates') and _has_any(w, 'load', 'loading', 'unload', 'unloading'), ['transport_caravans']),
    (lambda fn, w: _has_any(w, 'crate', 'crates'), ['transport_crates']),
    (lambda fn, w: 'raft' in w and _has_any(w, 'unstuck', 'convert', 'movement', 'equip'), ['transport_caravans']),
    (lambda fn, w: 'raft' in w and 'ground' in w, ['transport_caravans']),
    (lambda fn, w: 'raft' in w, ['transport_caravans']),
    (lambda fn, w: 'wagon' in w, ['transport_caravans']),

    # =====================================================================
    # 6. MOUNTS (before combat — mount actions are not combat)
    # =====================================================================
    (lambda fn, w: 'mount' in w and _has_any(w, 'summon', 'dismiss', 'mounting', 'unmounting',
                                               'flourish', 'ride', 'swimming', 'spawning',
                                               'despawning', 'dismount', 'anchor', 'rowboat',
                                               'terrorbird', 'alpine'), ['mounts']),
    (lambda fn, w: fn.startswith('mount_') or 'mount_' in fn, ['mounts']),
    (lambda fn, w: fn.startswith('flyingmount') or 'flying_mount' in fn, ['mounts']),
    (lambda fn, w: fn.startswith('summoning_') and 'mount' in w, ['mounts']),
    (lambda fn, w: 'mounts' in w, ['mounts']),
    (lambda fn, w: 'flying' in w and _has_any(w, 'around', 'verra', 'ocean'), ['mounts']),
    (lambda fn, w: 'mounted' in w and 'running' in w, ['mounts']),

    # =====================================================================
    # 7. NODES (before combat — node actions are governance)
    # =====================================================================
    (lambda fn, w: 'node' in w, ['nodes']),
    (lambda fn, w: 'mayor' in w or 'mayoral' in w, ['nodes']),
    (lambda fn, w: 'citizen' in w or 'citizenship' in w, ['nodes']),
    (lambda fn, w: 'siege' in w, ['nodes']),
    (lambda fn, w: 'sheriff' in w or 'sherrif' in w, ['nodes']),
    (lambda fn, w: 'taxes' in w or 'taxvoucher' in w or 'taxvouchers' in w, ['nodes']),
    (lambda fn, w: 'boon' in w and 'status' in w, ['nodes']),
    (lambda fn, w: 'submitting' in w and 'vote' in w, ['nodes']),

    # =====================================================================
    # 8. WORLD EVENTS (before combat/character — events have their own folder)
    # =====================================================================
    (lambda fn, w: 'event' in w and _has_any(w, 'phase', 'start', 'collect', 'reward',
                                               'defender', 'attacker', 'abandoned', 'expired',
                                               'finditem', 'prepare', 'launch'), ['world_events']),
    (lambda fn, w: 'harbinger' in w, ['world_events', 'harbinger']),

    # =====================================================================
    # 9. ECONOMY / MARKETPLACE
    # =====================================================================
    (lambda fn, w: 'marketplace' in w or 'market' in w, ['economy']),
    (lambda fn, w: fn.startswith('market_'), ['economy']),
    (lambda fn, w: 'vendor' in w and _has_any(w, 'buy', 'sell', 'items', 'materials', 'general'), ['economy']),
    (lambda fn, w: 'vendor' in w, ['economy']),
    (lambda fn, w: fn.startswith('buy_'), ['economy']),
    (lambda fn, w: fn.startswith('selling_'), ['economy']),
    (lambda fn, w: 'buyorder' in fn or 'buy_order' in fn, ['economy']),
    (lambda fn, w: 'requisition' in w, ['economy']),

    # =====================================================================
    # 10. TRADING
    # =====================================================================
    (lambda fn, w: fn.startswith('trade_') or fn.startswith('trading_'), ['social_trading']),
    (lambda fn, w: 'trading' in w and 'while' not in w, ['social_trading']),

    # =====================================================================
    # 11. NPC INTERACTION (crafting station NPCs, vendor talk, etc.)
    # =====================================================================
    (lambda fn, w: _has_any(w, *CRAFTING_STATIONS) and _has_any(w, 'items', 'materials'), ['world_npc_interaction']),
    (lambda fn, w: _has_any(w, *CRAFTING_STATIONS), ['world_npc_interaction']),
    (lambda fn, w: 'npc' in w and _has_any(w, 'vendor', 'interact', 'general'), ['world_npc_interaction']),
    (lambda fn, w: 'commodityvendor' in fn, ['world_npc_interaction']),
    (lambda fn, w: 'artisan' in w and 'commodityvendor' in fn, ['world_npc_interaction']),

    # =====================================================================
    # 12. MOVEMENT (before combat — these aren't combat actions)
    # =====================================================================
    (lambda fn, w: _has_any(w, 'jumping', 'swimming') and not _has_any(w, 'mount', 'corsair'), ['generic', 'movement']),
    (lambda fn, w: 'running' in w and 'walking' in w, ['generic', 'movement']),
    (lambda fn, w: 'running' in w and not _has_any(w, 'mount', 'mounted', 'caravan', 'corsair'), ['generic', 'movement']),
    (lambda fn, w: 'dodge' in w, ['generic', 'movement']),
    (lambda fn, w: 'run' in w and len(fn.split('_')) <= 5, ['generic', 'movement']),
    (lambda fn, w: _has_any(w, 'transition') and 'between' in w, ['generic', 'movement']),
    (lambda fn, w: 'stand' in w and 'sit' in w, ['generic']),
    # compass directions = server worker boundary captures
    (lambda fn, w: re.search(r'sw\d+_to_sw\d+', fn) is not None, ['server_workers']),
    (lambda fn, w: 'across' in w and 'sws' in fn, ['server_workers']),
    (lambda fn, w: w & {'east', 'west', 'south', 'north'} and not _has_any(w, 'combat', 'quest', 'gather'), ['server_workers']),

    # =====================================================================
    # 13. STORAGE / INVENTORY
    # =====================================================================
    (lambda fn, w: 'guild' in w and 'storage' in w, ['ui_inventory_management']),
    (lambda fn, w: 'storage' in w and _has_any(w, 'move', 'expand', 'add', 'glint', 'tab', 'item'), ['ui_inventory_management']),
    (lambda fn, w: 'storage' in w, ['ui_inventory_management']),
    (lambda fn, w: fn.startswith('inventory_'), ['ui_inventory_management']),
    (lambda fn, w: 'inventory' in w and _has_any(w, 'move', 'repair', 'delete', 'open', 'drop',
                                                   'pickup', 'expand', 'use', 'buy', 'add',
                                                   'crowbar', 'abandon', 'combine', 'stack'), ['ui_inventory_management']),
    (lambda fn, w: 'inventory' in w, ['ui_inventory_management']),

    # =====================================================================
    # 14. EQUIPMENT / EQUIP-UNEQUIP
    # =====================================================================
    (lambda fn, w: 'equipment' in w and _has_any(w, 'equip', 'unequip', 'hide', 'unhide',
                                                   'belt', 'boots', 'bracers', 'cape', 'chest',
                                                   'earring', 'gloves', 'helmet', 'necklace',
                                                   'melee', 'ranged', 'costume', 'ring', 'sheild',
                                                   'shield', 'greatsword', 'focus'), ['ui_inventory_management', 'equip_unequip']),
    (lambda fn, w: 'equipment' in w and 'artisan' in w, ['artisan']),
    (lambda fn, w: 'equipment' in w, ['ui_inventory_management', 'equip_unequip']),
    (lambda fn, w: fn.startswith('equip_') or fn.startswith('unequip_'), ['ui_inventory_management', 'equip_unequip']),
    (lambda fn, w: fn.startswith('equipping_') or fn.startswith('unequipping_'), ['ui_inventory_management', 'equip_unequip']),
    (lambda fn, w: 'cosmetic' in w and _has_any(w, 'equip', 'unequip'), ['ui_inventory_management', 'equip_unequip']),

    # =====================================================================
    # 15. ITEM USAGE (item_use, item_equip, etc.)
    # =====================================================================
    (lambda fn, w: fn.startswith('item_') and _has_any(w, 'equip', 'unequip'), ['ui_inventory_management', 'equip_unequip']),
    (lambda fn, w: fn.startswith('item_') and 'use' in w, ['ui_inventory_management']),
    (lambda fn, w: fn.startswith('item_'), ['ui_inventory_management']),

    # =====================================================================
    # 16. CHARACTER (skill points, character screen, etc.)
    # =====================================================================
    (lambda fn, w: 'character' in w and 'investskillpoint' in fn, ['character']),
    (lambda fn, w: 'character' in w and 'equipment' in w, ['character']),
    (lambda fn, w: 'character' in w and _has_any(w, 'block', 'action', 'mode'), ['character']),
    (lambda fn, w: 'invest' in w and _has_any(w, 'burning', 'chilling', 'volatile', 'keen',
                                                'echo', 'prism', 'ward'), ['character']),

    # =====================================================================
    # 17. ARTISAN / CRAFTING
    # =====================================================================
    (lambda fn, w: 'artisan' in w, ['artisan']),
    (lambda fn, w: 'crafting' in w and not _has_any(w, 'crate', 'crates'), ['artisan', 'crafting']),
    (lambda fn, w: 'craft' in w and 'item' in w and not _has_any(w, 'crate', 'crates'), ['artisan', 'crafting']),

    # =====================================================================
    # 18. SOCIAL
    # =====================================================================
    (lambda fn, w: 'friend' in w and _has_any(w, 'add', 'remove', 'invite'), ['friend_management']),
    (lambda fn, w: 'guild' in w and _has_any(w, 'invite', 'leave', 'join', 'being', 'leaving', 'create', 'creating'), ['guild_management']),
    (lambda fn, w: 'party' in w and _has_any(w, 'invite', 'promote', 'leave', 'kick'), ['party_management']),
    (lambda fn, w: _has_any(w, 'chat', 'whisper'), ['social_communication']),
    (lambda fn, w: 'link' in w and 'item' in w and _has_any(w, 'chat', 'hat'), ['social_communication']),
    (lambda fn, w: 'talking' in w and _has_any(w, 'guild', 'party', 'chat'), ['social_communication']),
    (lambda fn, w: 'mail' in w or 'mailbox' in w, ['social']),
    (lambda fn, w: 'social' in w and 'menu' in w, ['social']),

    # =====================================================================
    # 19. COMBAT / PVP / PVE
    # =====================================================================
    (lambda fn, w: _has_any(w, 'pvp', 'duel', 'arena'), ['combat_pvp']),
    (lambda fn, w: _has_any(w, 'flagged', 'flagging', 'corrupt', 'combatant'), ['combat_pvp']),
    (lambda fn, w: 'flag' in w and 'purple' in w, ['combat_pvp']),
    (lambda fn, w: 'expiring' in w and 'flag' in fn, ['combat_pvp']),
    (lambda fn, w: 'combat' in w and 'pve' in w, ['combat_pve']),
    (lambda fn, w: 'combat' in w, ['combat']),
    (lambda fn, w: 'ability' in w and 'rotation' in w, ['combat_pve']),
    (lambda fn, w: fn.startswith('skill_'), ['combat_pve']),
    (lambda fn, w: 'aggro' in w, ['combat_npc_trigger']),
    (lambda fn, w: 'trigger' in w and _has_any(w, 'npc', 'guard'), ['combat_npc_trigger']),
    (lambda fn, w: 'kill' in w and not _has_any(w, 'caravan', 'wagon'), ['combat_pve']),
    (lambda fn, w: 'basic' in w and _has_any(w, 'attacks', 'atk', 'attack'), ['combat_pve']),
    # Skill augments / combat abilities (no class context in filename)
    (lambda fn, w: 'damage' in w and _has_any(w, 'focus', 'finisher', 'projectile', 'proc'), ['combat_pve']),
    (lambda fn, w: 'finisher' in w and _has_any(w, 'damage', 'chance', 'extented', 'extended'), ['combat_pve']),
    (lambda fn, w: 'proc' in w and _has_any(w, 'finisher', 'duration'), ['combat_pve']),
    (lambda fn, w: 'projectile' in w and 'damage' in w, ['combat_pve']),
    (lambda fn, w: _has_any(w, 'combofull', 'combo') and not _has_any(w, 'caravan'), ['combat_pve']),
    (lambda fn, w: _has_any(w, 'empowered', 'righteous', 'ward', 'fortification',
                             'smite', 'bless', 'blessed'), ['combat_pve']),
    (lambda fn, w: 'looting' in w, ['combat_pve']),
    (lambda fn, w: _has_any(w, 'axe', 'sword', 'greatsword', 'bow', 'longbow', 'shortbow',
                             'dagger', 'daggers', 'mace', 'rapier', 'wand', 'spellbook',
                             'focus') and detect_archetype(w) is not None, ['combat_pve']),
    (lambda fn, w: 'switch' in w and 'weapon' in w, ['ui_inventory_management', 'equip_unequip']),
    (lambda fn, w: 'items' in w and _has_any(w, 'unequipped', 'uneqipped', 'equipped'), ['ui_inventory_management']),
    (lambda fn, w: 'putting' in w and 'item' in w, ['economy']),
    (lambda fn, w: 'trying' in w and 'trading' in w, ['social_trading']),
    (lambda fn, w: 'everything' in w, ['generic']),

    # =====================================================================
    # 20. QUEST
    # =====================================================================
    (lambda fn, w: 'quest' in w, ['quest']),

    # =====================================================================
    # 21. SERVER WORKERS
    # =====================================================================
    (lambda fn, w: 'server' in w and 'worker' in w, ['server_workers']),

    # =====================================================================
    # 22. OCEAN / NAVAL
    # =====================================================================
    (lambda fn, w: _has_any(w, 'ocean', 'naval'), ['ocean']),

    # =====================================================================
    # 23. GENERIC UI
    # =====================================================================
    (lambda fn, w: 'respawn' in w, ['generic']),
    (lambda fn, w: 'load' in w and 'screen' in w, ['generic']),
    (lambda fn, w: 'interactable' in w, ['generic']),
    (lambda fn, w: 'store' in w and 'menu' in w, ['generic']),
    (lambda fn, w: 'map' in w and 'open' in w, ['ui_inventory_management']),
    (lambda fn, w: 'dying' in w or 'death' in w, ['generic']),
    (lambda fn, w: 'loggin' in fn or 'logging_in' in fn, ['generic']),
    (lambda fn, w: fn.startswith('aoc_action_') and 'mount' not in w, ['generic']),

    # =====================================================================
    # 24. MATERIAL VALUE FILES (color + value → world_gathering)
    # =====================================================================
    (lambda fn, w: bool(w & MATERIALS) and _has_any(w, 'blue', 'green', 'grey', 'purple', 'white'), ['world_gathering']),
    (lambda fn, w: bool(w & MATERIALS) and 'sand' in w, ['world_processing']),

    # =====================================================================
    # 25. PLAYER-GENERIC ACTIONS (last resort)
    # =====================================================================
    (lambda fn, w: fn.startswith('player_') and _has_any(w, 'harvest', 'start'), ['world_gathering']),
    (lambda fn, w: fn.startswith('player_') and _has_any(w, 'vendor', 'buy'), ['economy']),
    (lambda fn, w: fn.startswith('player_') and _has_any(w, 'crate', 'crates', 'payout'), ['transport_crates']),
    (lambda fn, w: fn.startswith('player_') and 'trade' in w, ['social_trading']),
    (lambda fn, w: fn.startswith('player_') and 'put' in w and 'storage' in w, ['ui_inventory_management']),

    # =====================================================================
    # 26. BEING INVITED (social action, not combat)
    # =====================================================================
    (lambda fn, w: 'being' in w and 'invited' in w, ['guild_management']),
    (lambda fn, w: 'retrieving' in w and _has_any(w, 'silver', 'gold'), ['economy']),
    (lambda fn, w: 'npc_interaction' in fn or ('npc' in w and 'interaction' in w), ['world_npc_interaction']),
    (lambda fn, w: 'changing' in w and 'mayor' in fn, ['nodes']),
    (lambda fn, w: 'fruit' in w and 'salad' in w, ['world_processing']),
]


# ============================================================================
# HELPERS
# ============================================================================

def normalize(text: str) -> str:
    """Convert to lowercase snake_case."""
    text = text.lower()
    text = re.sub(r'[^\w]+', '_', text)
    text = re.sub(r'_+', '_', text)
    return text.strip('_')


def get_words(text: str) -> set:
    """Extract meaningful words (3+ chars) from text, including original compounds."""
    raw = text.lower()
    words = set(re.findall(r'[a-z]{3,}', raw))
    return words - STOP_WORDS


def get_positional_words(text: str) -> list:
    """Extract words from text preserving order (for fallback)."""
    raw = normalize(text)
    parts = raw.split('_')
    return [w for w in parts if len(w) >= 3 and w not in STOP_WORDS]


def detect_archetype(words: set) -> Optional[str]:
    """Detect player archetype/class. EXACT word match only."""
    for arch in ARCHETYPES:
        if arch in words:
            return arch
    for cls in CLASSES:
        if cls in words:
            return cls
    return None


def extract_aoc_topic(filename: str) -> Optional[str]:
    """
    For 'aoc_<prefix>_<topic>[_timestamp][_hexdump].pcap' files, extract the topic.
    The topic is what was captured, not who captured it.
    Handles: aoc_cleric_..., aoc_character_..., aoc_action_..., aoc_inventory_...
    """
    fn = normalize(Path(filename).stem)

    # Match aoc_<prefix>_<rest>  (rest may have timestamps, _hexdump, _1 suffix)
    m = re.match(r'^aoc_([a-z_]+?)_(.+?)(?:_\d{8}_\d{6})?(?:_\d+)?(?:_hexdump)?$', fn)
    if m:
        prefix = m.group(1)
        topic = m.group(2)
        if prefix in AOC_TOPIC_PREFIXES:
            return topic

    # Simpler: just aoc_<class>_<rest> without timestamps
    m = re.match(r'^aoc_([a-z]+)_(.+?)(?:_\d+)?$', fn)
    if m:
        prefix = m.group(1)
        topic = m.group(2)
        if prefix in AOC_TOPIC_PREFIXES:
            return topic

    return None


def parse_file_header(path: Path) -> dict:
    """Read '# Key: Value' metadata from the start of a file. Binary-safe."""
    meta = {}
    try:
        with open(path, 'rb') as f:
            raw = f.read(4096)
            text = raw.decode('utf-8', errors='ignore')
    except Exception:
        return meta

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith('#'):
            s = s.lstrip('#').strip()
            if ':' in s:
                k, v = s.split(':', 1)
                meta[k.strip().lower()] = v.strip()
        elif meta:
            break
    return meta


# ============================================================================
# CATEGORIZATION
# ============================================================================

def categorize_by_capture_target(capture_target: str, player_class: Optional[str]) -> Optional[List[str]]:
    """Map a capture target string to folder parts using regex rules."""
    ct = capture_target.strip()
    if not ct:
        return None

    for pattern, folder_parts in CAPTURE_TARGET_RULES:
        if re.search(pattern, ct, re.IGNORECASE):
            parts = list(folder_parts)
            # Add player class as subfolder for combat categories
            if parts and parts[0].startswith('combat') and player_class:
                arch = detect_archetype(set(player_class.lower().split()))
                if not arch:
                    arch = detect_archetype(get_words(player_class))
                if arch:
                    parts.append(arch)
            return parts

    return None


def categorize_by_filename(filename: str) -> Optional[List[str]]:
    """Analyze filename to determine folder. Handles aoc_<prefix>_<topic> pattern."""
    fn = normalize(Path(filename).stem)
    words = get_words(fn)

    # Handle aoc_<prefix>_<topic> pattern: the TOPIC determines the folder
    topic = extract_aoc_topic(filename)
    if topic:
        topic_words = get_words(topic)
        topic_fn = normalize(topic)
        for check_fn, folder_parts in FILENAME_RULES:
            if check_fn(topic_fn, topic_words):
                result = list(folder_parts)
                # For combat categories, add class from filename
                if result and result[0].startswith('combat'):
                    arch = detect_archetype(get_words(fn))
                    if arch:
                        result.append(arch)
                return result

    # Standard keyword matching on full filename
    for check_fn, folder_parts in FILENAME_RULES:
        if check_fn(fn, words):
            result = list(folder_parts)
            # For combat categories, add class from filename
            if result and result[0].startswith('combat'):
                arch = detect_archetype(words)
                if arch:
                    result.append(arch)
            return result

    return None


def categorize_file(filename: str, metadata: Optional[dict] = None) -> List[str]:
    """
    Determine correct folder for a file.
    Priority: header capture target > filename analysis > positional fallback.
    """
    capture_target = ''
    player_class = ''

    if metadata:
        capture_target = metadata.get('capture target', '') or metadata.get('capture_target', '')
        player_class = metadata.get('player class', '') or metadata.get('player_class', '')

    # 1. Header capture target (highest priority)
    if capture_target:
        result = categorize_by_capture_target(capture_target, player_class)
        if result:
            return result

    # 2. Filename analysis
    result = categorize_by_filename(filename)
    if result:
        return result

    # 3. Fallback: FIRST meaningful word BY POSITION in filename (not alphabetical)
    pos_words = get_positional_words(Path(filename).stem)
    # Skip class names — use first non-class word
    for w in pos_words:
        if w not in ALL_CLASS_NAMES:
            return [w]

    # If all words are class names, still use the first one
    if pos_words:
        return [pos_words[0]]

    return ['unsortable']


def get_clean_filename(original: str) -> str:
    """Normalize filename, preserve extension."""
    p = Path(original)
    base = normalize(p.stem)
    ext = p.suffix.lower()
    if ext not in ('.pcap', '.pcapng', '.cap'):
        ext = '.pcap'
    return f"{base}{ext}"


# ============================================================================
# FOLDER OPERATIONS
# ============================================================================

SKIP_DIRS = {'.git', '__pycache__', 'venv', 'node_modules', 'scripts',
             'needs_sorting', 'needs sorting', 'sorter'}


def remove_empty_dirs(root: Path, start_path: Path) -> List[str]:
    """Remove empty directories bottom-up."""
    deleted = []
    for dirpath, dirnames, filenames in os.walk(start_path, topdown=False):
        current = Path(dirpath)
        if current.name.lower() in SKIP_DIRS:
            continue
        try:
            if current.exists() and current.is_dir() and not any(current.iterdir()):
                current.rmdir()
                deleted.append(str(current.relative_to(root)))
        except (PermissionError, OSError):
            pass
    return deleted


# ============================================================================
# MAIN
# ============================================================================

def organize_pcaps(root: Path, dry_run: bool = False, reorganize: bool = False):
    """Main organization function."""

    if reorganize:
        print(f"Reorganizing: {root}")
        search_path = root
    else:
        search_path = root / 'Needs Sorting'
        if not search_path.exists():
            search_path.mkdir(parents=True, exist_ok=True)
            print(f"Created 'Needs Sorting' at {search_path}")
            print("Drop PCAPs there and run again.")
            return
        print(f"Processing: {search_path}")

    # Collect files
    pcap_files = []
    for dirpath, dirnames, filenames in os.walk(search_path):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith('.')]
        for filename in filenames:
            fp = Path(dirpath) / filename
            ext = fp.suffix.lower()
            if reorganize:
                if ext in ('.pcap', '.pcapng', '.cap') or not ext:
                    pcap_files.append(fp)
            else:
                pcap_files.append(fp)

    print(f"Found {len(pcap_files)} files")

    moved = 0
    skipped = 0
    unsortable_count = 0

    for src_file in pcap_files:
        metadata = parse_file_header(src_file)
        path_parts = categorize_file(src_file.name, metadata)

        dest_dir = root
        for part in path_parts:
            dest_dir = dest_dir / part

        new_filename = get_clean_filename(src_file.name)
        dest_file = dest_dir / new_filename

        # Already in the correct location?
        try:
            if src_file.resolve() == dest_file.resolve():
                skipped += 1
                continue
        except Exception:
            pass

        is_unsortable = 'unsortable' in path_parts
        if is_unsortable:
            unsortable_count += 1

        if dry_run:
            tag = "[?] " if is_unsortable else ""
            print(f"{tag}{src_file.relative_to(root)} -> {dest_file.relative_to(root)}")
            moved += 1
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            final = dest_file
            if final.exists():
                c = 1
                while True:
                    final = dest_dir / f"{dest_file.stem}_{c}{dest_file.suffix}"
                    if not final.exists():
                        break
                    c += 1
            try:
                shutil.move(str(src_file), str(final))
                print(f"Moved: {src_file.relative_to(root)} -> {final.relative_to(root)}")
                moved += 1
            except Exception as e:
                print(f"FAILED: {src_file.name}: {e}")

    # Cleanup empty directories
    if not dry_run and moved > 0:
        for d in remove_empty_dirs(root, search_path):
            print(f"Removed empty: {d}")

    mode = "DRY RUN" if dry_run else "DONE"
    print(f"\n{mode}: moved={moved} skipped={skipped} unsortable={unsortable_count}")


def main():
    parser = argparse.ArgumentParser(description="Ashes of Creation PCAP Organizer")
    parser.add_argument('--dry-run', '-n', action='store_true', help='Preview without moving')
    parser.add_argument('--reorganize', action='store_true', help='Re-sort entire repo')
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent

    print("=" * 60)
    print("Ashes of Creation PCAP Organizer")
    print("=" * 60)
    print(f"Root: {root}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    organize_pcaps(root, dry_run=args.dry_run, reorganize=args.reorganize)


if __name__ == '__main__':
    main()
