#!/usr/bin/env python3
"""
Ashes of Creation PCAP Organizer - Actually Works!

Moves FILES (not folders) from "Needs Sorting" into organized structure.
Creates folders as needed. Simple. Fast. Perfect.

Usage:
  python sort_aoc_pcaps.py [--dry-run] [--reorganize]
"""

import argparse
import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple


# ============================================================================
# ASHES OF CREATION KNOWLEDGE BASE
# ============================================================================

# Primary Archetypes
ARCHETYPES = {
    'tank', 'fighter', 'rogue', 'ranger',
    'mage', 'summoner', 'cleric', 'bard'
}

# All 64 Class Combinations
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

# Game Systems with their keywords
SYSTEMS = {
    'combat': {
        'keywords': ['combat', 'fight', 'battle', 'attack', 'damage', 'kill', 'death', 'pvp', 'pve', 'boss', 'raid', 'dungeon', 'corruption', 'flagging', 'pvx'],
        'subcategories': {
            'pvp': ['pvp', 'arena', 'duel', 'flagged', 'corrupted', 'open_world'],
            'pve': ['pve', 'dungeon', 'raid', 'boss', 'mob', 'elite', 'world_boss'],
        }
    },
    'nodes': {
        'keywords': ['node', 'settlement', 'city', 'town', 'village', 'metropolis', 'expedition', 'citizen', 'mayor', 'government'],
        'subcategories': {
            'siege': ['siege', 'attack', 'declare'],
            'defense': ['defend', 'defense', 'protect'],
            'development': ['build', 'construct', 'upgrade', 'contribution'],
        }
    },
    'caravans': {
        'keywords': ['caravan', 'transport', 'cargo', 'trade_route'],
        'subcategories': {
            'attack': ['attack', 'raid', 'brigand', 'highwayman'],
            'defense': ['defend', 'escort', 'guard', 'protect'],
            'running': ['run', 'transport', 'delivery', 'launch'],
        }
    },
    'sieges': {
        'keywords': ['siege', 'castle', 'relic', 'war', 'destruction'],
        'subcategories': {}
    },
    'world_events': {
        'keywords': ['event', 'harbinger', 'ancient', 'corruption_event', 'dynamic', 'trigger'],
        'subcategories': {
            'harbinger': ['harbinger', 'narthex', 'void', 'ancient_corruption'],
            'dynamic': ['dynamic', 'pop_up', 'trigger'],
        }
    },
    'artisan': {
        'keywords': ['artisan', 'craft', 'process', 'gather'],
        'subcategories': {
            'gathering': ['gather', 'mine', 'mining', 'herb', 'herbalism', 'lumber', 'fish', 'fishing', 'skin'],
            'processing': ['process', 'smelt', 'tan', 'weave', 'mill', 'stone'],
            'crafting': ['craft', 'smith', 'blacksmith', 'alchemy', 'cook', 'enchant', 'carpenter', 'tailor'],
        }
    },
    'economy': {
        'keywords': ['trade', 'buy', 'sell', 'auction', 'shop', 'vendor', 'gold', 'currency', 'market', 'broker'],
        'subcategories': {}
    },
    'social': {
        'keywords': ['chat', 'whisper', 'guild', 'party', 'group', 'friend', 'mail', 'alliance'],
        'subcategories': {}
    },
    'housing': {
        'keywords': ['housing', 'freehold', 'apartment', 'furniture', 'decoration'],
        'subcategories': {}
    },
    'ocean': {
        'keywords': ['ocean', 'naval', 'ship', 'sea', 'underwater', 'port', 'maritime'],
        'subcategories': {}
    },
    'mounts': {
        'keywords': ['mount', 'mounts', 'flyingmount', 'flying', 'horse', 'ride', 'ridable', 'saddle'],
        'subcategories': {}
    },
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def normalize(text: str) -> str:
    """Convert to lowercase snake_case."""
    import re
    text = text.lower()
    text = re.sub(r'[^\w]+', '_', text)
    text = re.sub(r'_+', '_', text)
    return text.strip('_')


def get_words(text: str) -> List[str]:
    """Extract individual words from text."""
    import re
    # Prefer pure alphabetic word tokens so things like "smite3" -> "smite"
    raw = text.lower()
    words = re.findall(r'[a-z]+', raw)

    # Filter out short/common noise words that shouldn't become folders
    STOP_WORDS = {
        'aoc', 'pcap', 'capture', 'file', 'data', 'test', 'final', 'finale',
        'perfect', 'good', 'best', 'fixed', 'clean', 'v1', 'v2', 'copy', 'old'
    }

    return [w for w in words if len(w) > 1 and w not in STOP_WORDS]


def matches_existing_folder(filename: str, existing_folders: List[str]) -> Optional[str]:
    """Check if filename matches any existing folder."""
    fname_norm = normalize(filename)
    fname_words = set(get_words(filename))
    
    best_match = None
    best_score = 0
    
    for folder_path in existing_folders:
        folder_parts = folder_path.split('/')
        score = 0
        
        # Check each part of the folder path
        for part in folder_parts:
            part_norm = normalize(part)
            part_words = set(get_words(part))
            
            # Direct prefix match (e.g., "processing_x" matches "world_processing")
            # Strong direct prefix match only for reasonably long parts
            if len(part_norm) > 4 and (fname_norm.startswith(part_norm + '_') or fname_norm.startswith(part_norm)):
                score += len(part_norm) * 10
            
            # Word overlap (exact token matches are the strongest signal)
            overlap = len(fname_words & part_words)
            if overlap > 0:
                score += overlap * 30
            
            # Any part word substring in filename (weaker signal)
            for word in part_words:
                if len(word) > 2 and word in fname_norm and word not in fname_words:
                    score += len(word) * 5
        
        if score > best_score:
            best_score = score
            best_match = folder_path
    
    # Only return if score is significant
    return best_match if best_score > 20 else None


def detect_system(words: List[str]) -> Optional[Tuple[str, Optional[str]]]:
    """
    Detect game system and subcategory from words.
    Returns: (system_name, subcategory_name) or None
    """ 
    word_set = set(words)
    
    for system_name, system_data in SYSTEMS.items():
        # Check if any system keyword matches
        system_keywords = set(system_data['keywords'])
        if word_set & system_keywords:
            # Found system, now check for subcategory
            for subcat_name, subcat_keywords in system_data['subcategories'].items():
                if word_set & set(subcat_keywords):
                    return (system_name, subcat_name)
            # System found but no subcategory
            return (system_name, None)
    
    return None


def detect_archetype(words: List[str]) -> Optional[str]:
    """Detect character archetype/class from words."""
    word_set = set(words)
    
    # Check primary archetypes first
    for archetype in ARCHETYPES:
        if archetype in word_set:
            return archetype
    
    # Check class combinations
    for class_name in CLASSES:
        if class_name in word_set:
            return class_name
    
    # Check partial matches
    for word in words:
        for archetype in ARCHETYPES:
            if archetype in word or word in archetype:
                return archetype
        for class_name in CLASSES:
            if class_name in word or word in class_name:
                return class_name
    
    return None


def is_skill_ability(words: List[str]) -> bool:
    """Check if this appears to be a skill/ability capture."""
    skill_words = {'skill', 'ability', 'spell', 'cast', 'attack', 'heal', 'buff', 'debuff', 'ultimate', 'rotation', 'combo'}
    return bool(set(words) & skill_words)


def categorize_file(filename: str, existing_folders: List[str]) -> List[str]:
    """
    Figure out where this file should go.
    Returns list of folder parts, e.g., ['combat', 'pvp', 'tank']
    """
    # STEP 1: Check if it matches an existing folder
    existing_match = matches_existing_folder(filename, existing_folders)
    if existing_match:
        return existing_match.split('/')
    
    # STEP 2: Analyze the filename
    words = get_words(filename)
    
    if not words:
        return ['unsortable']
    
    path_parts = []
    
    # Detect game system
    system_info = detect_system(words)
    if system_info:
        system_name, subcategory = system_info
        path_parts.append(system_name)
        if subcategory:
            path_parts.append(subcategory)
    
    # Detect archetype (for combat/skills)
    archetype = detect_archetype(words)
    if archetype and (not path_parts or path_parts[0] == 'combat'):
        if not path_parts:
            path_parts = ['combat']
        path_parts.append(archetype)
    
    # Fallback: use first meaningful word
    if not path_parts:
        first_word = words[0]
        if first_word not in {'pcap', 'capture', 'file', 'data', 'test'}:
            path_parts.append(first_word)
        else:
            path_parts.append('unsortable')
    
    return path_parts


def get_new_filename(original: str, path_parts: List[str]) -> str:
    """Generate the new filename with proper extension and skill_ prefix if needed."""
    p = Path(original)
    base = normalize(p.stem)
    ext = p.suffix.lower()
    
    # Ensure proper extension
    if not ext or ext not in ['.pcap', '.pcapng', '.cap']:
        ext = '.pcap'
    
    # Add skill_ prefix if this is a skill and we have an archetype in the path
    words = get_words(base)
    if is_skill_ability(words):
        # Check if path has an archetype
        has_archetype = any(part in ARCHETYPES or part in CLASSES for part in path_parts)
        if has_archetype and not base.startswith('skill_'):
            base = f"skill_{base}"
    
    return f"{base}{ext}"


def scan_existing_folders(root: Path) -> List[str]:
    """Scan repo for existing folder structures."""
    folders = []
    skip = {'git', '__pycache__', 'venv', 'node_modules', 'scripts', 'needs_sorting'}
    
    def walk(path: Path, depth: int, parts: List[str]):
        if depth > 5:
            return
        
        try:
            for child in path.iterdir():
                if not child.is_dir():
                    continue
                
                child_norm = normalize(child.name)
                if child_norm in skip:
                    continue
                
                new_parts = parts + [child_norm]
                folders.append('/'.join(new_parts))
                walk(child, depth + 1, new_parts)
        except PermissionError:
            pass
    
    walk(root, 0, [])
    return folders


def remove_empty_dirs(root: Path, start_path: Path):
    """Remove empty directories bottom-up."""
    skip = {'git', '__pycache__', 'venv', 'node_modules', 'scripts'}
    deleted = []
    
    for dirpath, dirnames, filenames in os.walk(start_path, topdown=False):
        current = Path(dirpath)
        
        # Skip protected directories
        if any(s in current.parts for s in skip):
            continue
        
        # Check if empty
        try:
            if current.exists() and current.is_dir() and not any(current.iterdir()):
                current.rmdir()
                deleted.append(str(current.relative_to(root)))
        except (PermissionError, OSError):
            pass
    
    return deleted


# ============================================================================
# MAIN PROCESSING
# ============================================================================

def organize_pcaps(root: Path, dry_run: bool = False, reorganize: bool = False):
    """Main function - organize all the PCAPs!"""
    
    # Determine what to process
    if reorganize:
        print(f"🔄 Reorganizing entire repository: {root}")
        search_path = root
    else:
        search_path = root / 'Needs Sorting'
        if not search_path.exists():
            search_path.mkdir(parents=True, exist_ok=True)
            print(f"✅ Created 'Needs Sorting' folder: {search_path}")
            print(f"📥 Drop your PCAPs here and run again!")
            return
        print(f"📂 Processing: {search_path}")
    
    # Scan existing folder structure
    print(f"🔍 Scanning existing folders...")
    existing_folders = scan_existing_folders(root)
    if existing_folders:
        print(f"📁 Found {len(existing_folders)} existing folders")
        for folder in sorted(existing_folders[:5]):
            print(f"   - {folder}")
        if len(existing_folders) > 5:
            print(f"   ... and {len(existing_folders) - 5} more")
    
    print()
    print("="*60)
    
    # Collect all PCAP files
    pcap_files = []
    skip_dirs = {'git', '__pycache__', 'venv', 'node_modules', 'scripts'}
    
    for dirpath, dirnames, filenames in os.walk(search_path):
        # Filter directories
        dirnames[:] = [d for d in dirnames if normalize(d) not in skip_dirs]
        # When reorganizing we want to traverse existing folders too so files
        # can be moved into their correct places. We only filter out skip_dirs
        # (handled above).
        
        for filename in filenames:
            file_path = Path(dirpath) / filename
            ext = file_path.suffix.lower()
            # When reorganizing the whole repo, only consider pcap files.
            # When processing the 'Needs Sorting' folder (normal run), include
            # all files so the folder can be emptied (txt, hexdump, etc.).
            if reorganize:
                if ext in ['.pcap', '.pcapng', '.cap'] or not ext:
                    pcap_files.append(file_path)
            else:
                pcap_files.append(file_path)
    
    print(f"📊 Found {len(pcap_files)} PCAP files to process")
    print()
    
    # Process each file
    moved = 0
    skipped = 0
    unsortable = 0
    
    for src_file in pcap_files:
        filename = src_file.name
        
        # Categorize
        path_parts = categorize_file(filename, existing_folders)
        
        # Build destination
        dest_dir = root
        for part in path_parts:
            dest_dir = dest_dir / part
        
        new_filename = get_new_filename(filename, path_parts)
        dest_file = dest_dir / new_filename
        
        # Check if already in right place
        try:
            if src_file.resolve() == dest_file.resolve():
                skipped += 1
                continue
        except:
            pass
        
        # Track unsortable
        is_unsortable = 'unsortable' in path_parts
        if is_unsortable:
            unsortable += 1
        
        # Show what we're doing
        if dry_run:
            icon = "⚠️ " if is_unsortable else "🔍"
            print(f"{icon} {src_file.relative_to(root)}")
            print(f"   → {dest_file.relative_to(root)}")
            if is_unsortable:
                print(f"   (couldn't categorize - rename with better keywords)")
            moved += 1
        else:
            # Create destination directory
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Handle duplicates
            final_dest = dest_file
            if final_dest.exists():
                counter = 1
                while True:
                    final_dest = dest_dir / f"{dest_file.stem}_{counter}{dest_file.suffix}"
                    if not final_dest.exists():
                        break
                    counter += 1
            
            # Move it!
            try:
                shutil.move(str(src_file), str(final_dest))
                icon = "⚠️ " if is_unsortable else "✅"
                print(f"{icon} {src_file.relative_to(root)}")
                print(f"   → {final_dest.relative_to(root)}")
                if is_unsortable:
                    print(f"   (couldn't categorize - please review!)")
                moved += 1
            except Exception as e:
                print(f"❌ Failed to move {filename}: {e}")
    
    # After processing, any remaining files still inside any 'Needs Sorting'
    # directories should be moved to an 'unsortable' folder so nothing is
    # left behind for manual review.
    needs_dirs = []
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            if normalize(d) == 'needs_sorting':
                needs_dirs.append(Path(dirpath) / d)

    remaining_in_needs = []
    for nd in needs_dirs:
        for child in nd.iterdir():
            if child.is_file():
                # Include any filetype left in Needs Sorting so we don't leave
                # miscellaneous files behind (hexdumps, txt, etc.).
                remaining_in_needs.append(child)

    if remaining_in_needs:
        unsort_dir = root / 'unsortable'
        if dry_run:
            print()
            print("⚠️ Remaining files in 'Needs Sorting' (dry-run):")
            for f in remaining_in_needs:
                print(f"   - {f.relative_to(root)} -> {unsort_dir.relative_to(root)}/{f.name}")
        else:
            unsort_dir.mkdir(parents=True, exist_ok=True)
            print()
            print("⚠️ Moving leftover files from 'Needs Sorting' to 'unsortable/'")
            for f in remaining_in_needs:
                final = unsort_dir / f.name
                if final.exists():
                    counter = 1
                    while True:
                        final = unsort_dir / f"{final.stem}_{counter}{final.suffix}"
                        if not final.exists():
                            break
                        counter += 1
                try:
                    shutil.move(str(f), str(final))
                    print(f"   → {f.relative_to(root)} -> {final.relative_to(root)}")
                    moved += 1
                except Exception as e:
                    print(f"   ❌ Failed to move leftover {f.name}: {e}")

    # Clean up empty folders
    if not dry_run and moved > 0:
        print()
        print("="*60)
        print("🧹 Cleaning up empty directories...")
        deleted = remove_empty_dirs(root, search_path)
        if deleted:
            for d in deleted:
                print(f"🗑️  Deleted empty: {d}")
    
    # Summary
    print()
    print("="*60)
    if dry_run:
        print("🔍 DRY RUN COMPLETE")
        print(f"   Would move: {moved} files")
        print(f"   Would skip: {skipped} files")
        if unsortable > 0:
            print(f"   ⚠️  Unsortable: {unsortable} files")
            print(f"   💡 Tip: Rename with AoC keywords (tank, caravan, node, etc.)")
    else:
        print("✅ ORGANIZATION COMPLETE")
        print(f"   Moved: {moved} files")
        print(f"   Skipped: {skipped} files")
        if unsortable > 0:
            print(f"   ⚠️  Unsortable: {unsortable} files → check 'unsortable/' folder")
            print(f"   💡 Rename them and run again for proper categorization!")
        
        if moved > 0:
            print()
            print("✨ All done! Your PCAPs are organized! Thank the holy AI spirits! ✨")


def main():
    parser = argparse.ArgumentParser(description="Ashes of Creation PCAP Organizer")
    parser.add_argument('--dry-run', '-n', action='store_true', 
                       help='Preview changes without moving files')
    parser.add_argument('--reorganize', action='store_true',
                       help='Reorganize entire repo (use with caution!)')
    args = parser.parse_args()
    
    # Find root (parent of script directory)
    root = Path(__file__).resolve().parent.parent
    
    print("="*60)
    print("🎮 Ashes of Creation PCAP Organizer")
    print("="*60)
    print(f"📍 Root: {root}")
    print(f"🔧 Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("="*60)
    print()
    
    organize_pcaps(root, dry_run=args.dry_run, reorganize=args.reorganize)


if __name__ == '__main__':
    main()