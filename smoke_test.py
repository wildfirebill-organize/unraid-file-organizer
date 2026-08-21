"""Quick smoke test: classifier + config + planner on a fake tree."""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from app.core.file_classifier import SmartFileClassifier
from app.core.config import ConfigManager
from app.services.scanner import ScannerService
from app.services.organizer import OrganizerService

tmp = Path(tempfile.mkdtemp())
print(f"Test root: {tmp}")

# Build a messy fake tree
files = {
    "downloads/foobar2000_v2.0_setup.exe": b"MZ" + b"\x00" * 100,
    "downloads/random_tool.exe": b"MZ" + b"\x00" * 50,
    "downloads/ubuntu-24.04-desktop-amd64.iso": b"\x00" * 10,
    "downloads/win11_23h2_x64.iso": b"\x00" * 10,
    "downloads/song.mp3": b"ID3" + b"\x00" * 20,
    "downloads/vacation_photo.jpg": b"\xff\xd8\xff\xe0" + b"\x00" * 20,
    "downloads/com.spotify.music.apk": b"PK\x03\x04" + b"\x00" * 30,
    "downloads/archive_backup.zip": b"PK\x03\x04" + b"\x00" * 40,
    "downloads/report.pdf": b"%PDF-1.7 " + b"\x00" * 20,
    "protected/appdata/db.sqlite": b"\x00" * 5,
}
for rel, content in files.items():
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)

# Config: allow downloads only; disallow protected/
cfg_path = tmp / "config.json"
cfg = ConfigManager(str(cfg_path))
cfg._config = cfg.load()
cfg._config.managed_paths = [type(cfg._config.managed_paths[0])(path=str(tmp / "downloads"), label="Downloads", enabled=True)]
cfg._config.disallow_paths = [type(cfg._config.disallow_paths[0])(path=str(tmp / "protected"), label="Protected")]
cfg.save()

scanner = ScannerService(cfg)
result = scanner.scan()
print(f"\nScanned {result.total_files} files from {result.roots_scanned}")
assert result.total_files == len(files) - 1, f"expected 9 files (protected skipped), got {result.total_files}"

classifier = SmartFileClassifier()
checks = [
    ("foobar2000_v2.0_setup.exe", "executable_windows", "music_player"),
    ("ubuntu-24.04-desktop-amd64.iso", "os_image", "os_component"),
    ("win11_23h2_x64.iso", "os_image", "os_component"),
    ("song.mp3", "media_audio", None),
    ("com.spotify.music.apk", "executable_android", "music_player"),
    ("archive_backup.zip", "archive", None),
    ("report.pdf", "document", None),
]
fails = 0
for fname, want_cat, want_intent in checks:
    cls = classifier.classify(tmp / "downloads" / fname)
    ok_cat = cls.category.value == want_cat
    ok_int = want_intent is None or cls.intent.value == want_intent
    status = "OK " if (ok_cat and ok_int) else "FAIL"
    if not (ok_cat and ok_int):
        fails += 1
    print(f"[{status}] {fname}: cat={cls.category.value} intent={cls.intent.value} conf={cls.confidence} dest={cls.suggested_location}")

# Plan + dry-run apply
organizer = OrganizerService(cfg)
plan = organizer.build_plan(result.items)
print(f"\nPlan: {len(plan.operations)} ops, conflicts={plan.conflicts}")
entry = organizer.apply_plan(plan, dry_run=False)
done = sum(1 for o in entry.operations if o.status == "done")
skipped = sum(1 for o in entry.operations if o.status == "skipped")
print(f"Applied: {done} done, {skipped} skipped")

# Verify protected file untouched
assert (tmp / "protected" / "appdata" / "db.sqlite").exists(), "PROTECTED FILE WAS TOUCHED!"
moved = list((tmp / "mnt").rglob("*")) if (tmp / "mnt").exists() else []
dests = [str(p.relative_to(tmp)) for p in tmp.rglob("*") if p.is_file() and "downloads" not in str(p.parent) and "protected" not in str(p.parent)]
print("\nFiles after organize:")
for d in sorted(dests):
    print(f"  {d}")

# Undo
undo = organizer.undo_last()
print(f"\nUndo: {undo['undone']} files restored")

# ---------- LLM assist logic (no Ollama needed — parser + enhance flow) ----------
from app.services.llm_classifier import LLMClassifier
from app.models.models import ScanResultItem, OrganizerConfig

llm = LLMClassifier()
p = llm.parse_response('{"category": "executable_windows", "intent": "game", "confidence": 0.9}')
assert p == ("executable_windows", "game", 0.9), f"valid parse failed: {p}"
assert llm.parse_response('{"category": "warp_drive", "intent": "game", "confidence": 0.9}') is None, "invalid category accepted"
assert llm.parse_response('{"category": "game", "intent": "warp_drive", "confidence": 0.9}') is None, "invalid intent accepted"
assert llm.parse_response('{"category": "game", "intent": "game", "confidence": 0.2}') is None, "low confidence accepted"
assert llm.parse_response('not json at all') is None, "garbage accepted"
assert llm.parse_response('{"category": "unknown", "intent": "unknown", "confidence": 0.9}') is None, "unknown accepted"
print("[OK ] LLM response parsing: valid/invalid/low-conf/garbage/unknown all handled")

cfg_llm = OrganizerConfig(llm_enabled=True, min_confidence=0.6)
items = [
    ScanResultItem(source_path="/x/mystery.exe", filename="mystery.exe", parent_dir="/x",
                   size_bytes=1000, category="unknown", intent="unknown", confidence=0.1,
                   details={"strings_sample": ["steam_api.dll", "d3d9.dll"]}),
    ScanResultItem(source_path="/x/highconf.mp3", filename="highconf.mp3", parent_dir="/x",
                   size_bytes=2000, category="media_audio", intent="data_file", confidence=0.8),
    ScanResultItem(source_path="/x/broken.bin", filename="broken.bin", parent_dir="/x",
                   size_bytes=3000, category="unknown", intent="unknown", confidence=0.1),
]
def fake_classify(item, cfg):
    if item.filename == "broken.bin":
        raise RuntimeError("simulated ollama failure")
    return ("executable_windows", "game", 0.85)
llm._classify_one = fake_classify
stats = llm.enhance(items, cfg_llm)
assert stats == {"candidates": 2, "upgraded": 1, "failed": 1}, f"bad stats: {stats}"
assert items[0].category == "executable_windows" and items[0].details.get("llm_assisted") is True
assert items[0].suggested_destination and "games" in items[0].suggested_destination
assert items[1].category == "media_audio" and "llm_assisted" not in items[1].details, "high-confidence file was sent to LLM"
print(f"[OK ] LLM enhance: {stats} — low-conf upgraded w/ destination, high-conf untouched, failure degraded")

# ---------- v1.2: custom rules + destination overrides (real scan) ----------
from app.models.models import CustomRule, ManagedPath, DisallowPath

(tmp / "downloads" / "game_dark_souls.exe").write_bytes(b"MZ" + b"\x00" * 30)
(tmp / "downloads" / "another_track.flac").write_bytes(b"fLaC" + b"\x00" * 20)

cfg2 = ConfigManager(str(tmp / "config2.json"))
c2 = cfg2.load()
c2.managed_paths = [ManagedPath(path=str(tmp / "downloads"), label="Downloads", enabled=True)]
c2.disallow_paths = []
c2.custom_rules = [CustomRule(
    name="games", pattern=r"^game_.*\.exe$", match_on="filename",
    category="executable_windows", intent="game",
    destination="/mnt/user/games/windows/",
)]
c2.category_destinations = {"media_audio": "/mnt/user/custom_music"}
cfg2.save()

scanner2 = ScannerService(cfg2)
r2 = scanner2.scan()
by_name = {i.filename: i for i in r2.items}

g = by_name["game_dark_souls.exe"]
assert g.category == "executable_windows" and g.intent == "game", f"rule cat/intent wrong: {g.category}/{g.intent}"
assert g.confidence >= 0.95 and g.details.get("rule_matched") == "games", f"rule not applied: conf={g.confidence}"
assert g.suggested_destination == "/mnt/user/games/windows/", f"rule dest wrong: {g.suggested_destination}"

f_ = by_name["another_track.flac"]
assert f_.category == "media_audio"
assert f_.suggested_destination == "/mnt/user/custom_music/", f"category override wrong: {f_.suggested_destination}"
assert "rule_matched" not in f_.details, "override leaked rule_matched tag"

s = by_name["song.mp3"]
assert s.suggested_destination == "/mnt/user/custom_music/", f"existing mp3 override wrong: {s.suggested_destination}"
print("[OK ] Custom rules: pattern matched, trusted confidence, dest override applied")
print("[OK ] Category destination overrides applied to matching categories")

# invalid regex must be rejected at config layer
c2.custom_rules.append(CustomRule(name="bad", pattern=r"[unclosed"))
try:
    cfg2.update(c2)
    raise AssertionError("invalid regex accepted")
except ValueError:
    pass
c2.custom_rules.pop()
c2.category_destinations["not_a_category"] = "/x"
try:
    cfg2.update(c2)
    raise AssertionError("invalid category accepted")
except ValueError:
    pass
c2.category_destinations.pop("not_a_category")
print("[OK ] Config validation rejects bad regex and unknown categories")

# ---------- v1.2: notifier payloads + scheduler math ----------
from app.services.notify import Notifier
from app.services.scheduler import ScanScheduler, build_digest, digest_message

n = Notifier()
d = n.build_payload("discord", "T", "M")
assert d == {"content": "**T**\nM"}, f"discord payload wrong: {d}"
assert n.build_payload("ntfy", "T", "M") == "M"
assert n.build_payload("generic", "T", "M") == {"title": "T", "message": "M"}
long = n.build_payload("discord", "T", "x" * 3000)
assert len(long["content"]) <= 2000, "discord limit not enforced"
print("[OK ] Notifier payload builders: discord/ntfy/generic + length limit")

now = datetime.utcnow()
assert ScanScheduler.next_run(None, 24, now) == now + timedelta(hours=24)
base = now - timedelta(hours=10)
assert ScanScheduler.next_run(base, 24, now) == base + timedelta(hours=24)
print("[OK ] Scheduler next_run math")

digest = build_digest(r2, c2)
assert digest["total_files"] == r2.total_files
assert digest["movable_files"] > 0 and digest["sample_moves"]
msg = digest_message(digest)
assert "ready to move" in msg
print(f"[OK ] Digest built: {digest['movable_files']} movable of {digest['total_files']}")

# ---------- v1.3: folder units, media library, duplicates, history ----------
from app.core.file_classifier import looks_like_app_folder
from app.services.media_library import parse_media, destination_for
from app.services.duplicates import DuplicateFinder
from app.services.history import read_history

# Folder units: game dir with exe + dlls moves whole
game_dir = tmp / "downloads" / "EldenRingPortable"
game_dir.mkdir(exist_ok=True)
(game_dir / "game_client.exe").write_bytes(b"MZ" + b"\x00" * 80)
for i in range(5):
    (game_dir / f"lib{i}.dll").write_bytes(b"MZ" + b"\x00" * 10)
assert looks_like_app_folder([f.name for f in game_dir.iterdir()]), "unit heuristic failed"
assert not looks_like_app_folder(["a.exe", "readme.txt"]), "false positive on tiny folder"

r3 = ScannerService(cfg2).scan()
units = [i for i in r3.items if i.details.get("folder_unit")]
assert len(units) == 1, f"expected 1 folder unit, got {len(units)}"
u = units[0]
assert u.filename == "EldenRingPortable" and u.intent == "game", f"unit misclassified: {u.filename}/{u.intent}"
assert u.suggested_destination == "/mnt/user/data/games/windows/", f"unit dest wrong: {u.suggested_destination}"
plan3 = OrganizerService(cfg2).build_plan(r3.items)
unit_op = next(o for o in plan3.operations if o.source == str(game_dir))
assert os.path.normpath(unit_op.destination) == os.path.normpath("/mnt/user/data/games/windows/EldenRingPortable"), f"planner dest wrong: {unit_op.destination}"
inner = [i for i in r3.items if i.parent_dir.startswith(str(game_dir))]
assert not inner, "scanner descended into folder unit"
print(f"[OK ] Folder unit: '{u.filename}' -> {u.suggested_destination} (no descent into it)")

# Media library parsing + routing
c2.media_library_enabled = True
c2.media_library_root = "/mnt/user/data/media"
cfg2.save()
(tmp / "downloads" / "Breaking Bad S01E02.mkv").write_bytes(b"\x00" * 20)
(tmp / "downloads" / "Inception (2010).mp4").write_bytes(b"\x00" * 20)
r4 = ScannerService(cfg2).scan()
by_name4 = {i.filename: i for i in r4.items}
ep = by_name4["Breaking Bad S01E02.mkv"]
mv = by_name4["Inception (2010).mp4"]
assert ep.details.get("media_parsed") == "episode"
assert ep.suggested_destination == "/mnt/user/data/media/tv/Breaking Bad/Season 01/", f"episode dest wrong: {ep.suggested_destination}"
assert mv.details.get("media_parsed") == "movie"
assert mv.suggested_destination == "/mnt/user/data/media/movies/Inception (2010)/", f"movie dest wrong: {mv.suggested_destination}"
assert parse_media("notes.txt") is None and parse_media("random_video.mkv") is None
print("[OK ] Media library: episode -> tv/.../Season 01/, movie -> movies/Title (Year)/")

# Duplicates: identical content in two files
dup_a = tmp / "downloads" / "dup_original.dat"
dup_b = tmp / "downloads" / "dup_copy.dat"
payload = os.urandom(2048)
dup_a.write_bytes(payload)
dup_b.write_bytes(payload)
finder = DuplicateFinder(cfg2)
rep = finder.find()
matching = [g for g in rep.groups if dup_a.name in str(g.files)]
assert len(matching) == 1, f"expected 1 group containing the dups, got {len(matching)}"
grp = matching[0]
assert set(grp.files) == {str(dup_a), str(dup_b)}, f"group files wrong: {grp.files}"
assert grp.keep == str(dup_a) or grp.keep == str(dup_b)
assert rep.wasted_bytes >= 2048
print(f"[OK ] Duplicates: 1 group found, keeper={Path(grp.keep).name}, wasted={rep.wasted_bytes}B")

# History recorded by scans
hist = read_history(limit=10)
assert len(hist) >= 3, f"expected >=3 history entries, got {len(hist)}"
triggers = {h.trigger for h in hist}
assert "manual" in triggers
latest = hist[-1]
assert latest.total_files > 0 and latest.movable_files > 0
print(f"[OK ] History: {len(hist)} entries recorded, triggers={sorted(triggers)}")

# ---------- v1.4: folder phase 2 + media enhancements ----------
from app.core.file_classifier import detect_folder_unit

# Nested unit: exe+dlls live in a bin/ subdir, top level has only misc files
nest = tmp / "downloads" / "ToolProSuite"
nest.mkdir(exist_ok=True)
(nest / "readme.txt").write_text("x")
(nest / "setup.cfg").write_text("y")
bin_ = nest / "bin"
bin_.mkdir(exist_ok=True)
(bin_ / "toolpro.exe").write_bytes(b"MZ" + b"\x00" * 60)
for i in range(4):
    (bin_ / f"core{i}.dll").write_bytes(b"MZ" + b"\x00" * 10)

info = detect_folder_unit(nest)
assert info is not None, "nested unit not detected"
assert info["primary_exe"] == "toolpro.exe", f"wrong primary: {info['primary_exe']}"

# Marker-only unit: tiny Steam-style folder (too small for the classic rule)
marker_dir = tmp / "downloads" / "SteamTiny"
marker_dir.mkdir(exist_ok=True)
(marker_dir / "game.exe").write_bytes(b"MZ" + b"\x00" * 20)
(marker_dir / "steam_api64.dll").write_bytes(b"MZ" + b"\x00" * 5)
(marker_dir / "steam_appid.txt").write_text("480")
assert detect_folder_unit(marker_dir) is not None, "launcher marker unit not detected"

# Engine-data unit: Godot-style exe + .pck
godot_dir = tmp / "downloads" / "GodotVNG"
godot_dir.mkdir(exist_ok=True)
(godot_dir / "GodotVNG.exe").write_bytes(b"MZ" + b"\x00" * 20)
(godot_dir / "game.pck").write_bytes(b"GDPC" + b"\x00" * 30)
ginfo = detect_folder_unit(godot_dir)
assert ginfo is not None and ginfo["primary_exe"] == "GodotVNG.exe", "engine-data unit not detected"

# Non-unit control stays untouched
plain = tmp / "downloads" / "vacation pics"
plain.mkdir(exist_ok=True)
(plain / "beach.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 10)
(plain / "hotel.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 10)
assert detect_folder_unit(plain) is None, "false positive on photo folder"

r5 = ScannerService(cfg2).scan()
units5 = {i.filename: i for i in r5.items if i.details.get("folder_unit")}
assert set(units5) >= {"ToolProSuite", "SteamTiny", "GodotVNG"}, f"missing units: {set(units5)}"
assert units5["ToolProSuite"].details.get("primary_exe") == "toolpro.exe"
inner5 = [i for i in r5.items if str(i.source_path).startswith(str(bin_))]
assert not inner5, "scanner descended into nested unit"
print(f"[OK ] Folder phase 2: {sorted(set(units5) & {'ToolProSuite','SteamTiny','GodotVNG'})} detected as units, no descent")

# Media enhancements
media_cases = [
    ("Show.Name.S01E02-E03.720p.mkv", ("episode", "Show Name", 1, 2), {"episode_end": 3}),
    ("[SubGroup] Cowboy Bebop - 05 [1080p].mkv", ("episode", "Cowboy Bebop", 1, 5), {}),
    ("Naruto Shippuden Episode 220.mp4", ("episode", "Naruto Shippuden", 1, 220), {}),
    ("Blade.Runner.2049.2017.1080p.x264.mkv", ("movie", "Blade Runner 2049", None, None), {"year": 2017}),
    ("The.Matrix.1999.mkv", ("movie", "The Matrix", None, None), {"year": 1999}),
]
for fname, expect, extra in media_cases:
    p = parse_media(fname)
    assert p is not None, f"{fname}: not parsed"
    assert (p["type"], p["title"], p.get("season"), p.get("episode")) == expect, f"{fname}: {p}"
    for k, v in extra.items():
        assert p.get(k) == v, f"{fname}: expected {k}={v}, got {p.get(k)}"

multi = parse_media("Show.Name.S01E02-E03.720p.mkv")
ep_dest = destination_for(multi, c2)
assert ep_dest == "/mnt/user/data/media/tv/Show Name/Season 01/", f"multi-ep dest wrong: {ep_dest}"

# Guard rails: no false positives on tricky names
assert parse_media("Blade Runner - 2049 (2017).mkv")["type"] == "movie"
assert parse_media("random_video.mkv") is None
assert parse_media("2020.720p.mkv") is None or True  # ambiguous — must not crash either way
print("[OK ] Media v1.4: multi-ep ranges, anime dash numbering, [group] prefixes, keyword eps, loose-year movies")

# ---------- keep-in-place rules (YouTube channel folders) ----------
c2.custom_rules.append(CustomRule(
    name="yt", pattern=r"YouTubeChannels", match_on="path", action="keep",
))
cfg2.save()
yt_dir = tmp / "downloads" / "YouTubeChannels" / "MKBHD"
yt_dir.mkdir(parents=True, exist_ok=True)
(yt_dir / "Cool Show S01E02.mkv").write_bytes(b"\x00" * 20)

r7 = ScannerService(cfg2).scan()
kept = [i for i in r7.items if i.details.get("rule_keep")]
assert len(kept) == 1 and kept[0].suggested_destination is None, \
    f"keep failed: {[(i.filename, i.suggested_destination) for i in kept]}"
kept_file = str(yt_dir / "Cool Show S01E02.mkv")
plan7 = OrganizerService(cfg2).build_plan(r7.items)
assert all(o.source != kept_file for o in plan7.operations), "kept file entered the plan"

# precedence control: identical file WITHOUT the keep rule routes into tv/
c2.custom_rules.pop()
cfg2.save()
r8 = ScannerService(cfg2).scan()
same = next(i for i in r8.items if i.source_path == kept_file)
assert same.details.get("media_parsed") == "episode" \
    and same.suggested_destination.startswith("/mnt/user/data/media/tv/"), \
    f"precedence control failed: {same.suggested_destination}"
print("[OK ] Keep-in-place rule: channel video untouched; without the rule it routes to tv/")

# ---------- ROM / console / homebrew / emulator classification ----------
rom_files = {
    "Super Mario World (USA).sfc": "snes",
    "Chrono Trigger.smc": "snes",
    "Super Mario Bros..nes": "nes",
    "Legend of Zelda - Ocarina of Time.z64": "n64",
    "Tetris.gb": "gb",
    "Pokemon Emerald Version.gba": "gba",
    "Mario Kart DS.nds": "nds",
    "Fire Emblem Awakening.3ds": "3ds",
    "Animal Crossing - New Leaf.cia": "3ds",
    "Zelda Breath of the Wild.nsp": "switch",
    "Mario Odyssey.xci": "switch",
    "Sonic the Hedgehog.sms": "sms",
    "Golden Axe.gen": "genesis",
    "Bonk's Revenge.pce": "pcengine",
    "Activision.a26": "atari2600",
    "Ms. Pac-Man.cdi": "dreamcast",
    "Harvest Moon.wbfs": "wii",
    "Twilight Princess.rvz": "wii",
}
for fname in rom_files:
    p = tmp / "downloads" / fname
    p.write_bytes(b"\x00" * 16)

homebrew_files = {"homebrew_menu.3dsx": "3ds", "usbloader_gx.dol": "wii", "RetroFlow.vpk": "psvita"}
for fname in homebrew_files:
    (tmp / "downloads" / fname).write_bytes(b"\x00" * 16)

(tmp / "downloads" / "epsxe.exe").write_bytes(b"MZ" + b"\x00" * 40)
(tmp / "downloads" / "Final Fantasy VII (USA).bin").write_bytes(b"\x00" * 16)
(tmp / "downloads" / "Tekken 3 PSX.bin").write_bytes(b"\x00" * 16)

for fname, want_console in rom_files.items():
    cls = classifier.classify(tmp / "downloads" / fname)
    assert cls.category.value == "game_rom", f"{fname}: cat={cls.category.value}"
    assert cls.details.get("console") == want_console, f"{fname}: console={cls.details.get('console')}"
    assert cls.suggested_location == f"/mnt/user/data/roms/{want_console}/", \
        f"{fname}: dest={cls.suggested_location}"
print(f"[OK ] ROMs: {len(rom_files)} consoles detected, each routed to data/roms/<console>/")

for fname, want_console in homebrew_files.items():
    cls = classifier.classify(tmp / "downloads" / fname)
    assert cls.category.value == "homebrew" and cls.details.get("console") == want_console, \
        f"{fname}: {cls.category.value}/{cls.details.get('console')}"
    assert cls.suggested_location == f"/mnt/user/data/homebrew/{want_console}/"
print("[OK ] Homebrew: 3dsx/dol/vpk -> data/homebrew/<console>/")

emu = classifier.classify(tmp / "downloads" / "epsxe.exe")
assert emu.intent.value == "emulator" and emu.suggested_location == "/mnt/user/data/emulators/windows/", \
    f"emulator wrong: {emu.intent.value}/{emu.suggested_location}"
print("[OK ] Emulator: epsxe.exe -> data/emulators/windows/")

# Ambiguous discs: region/console-word become ROMs; OS ISOs stay OS images
ff7 = classifier.classify(tmp / "downloads" / "Final Fantasy VII (USA).bin")
assert ff7.category.value == "game_rom" and ff7.details.get("console") == "disc", \
    f"region-tag disc failed: {ff7.category.value}/{ff7.details.get('console')}"
tekken = classifier.classify(tmp / "downloads" / "Tekken 3 PSX.bin")
assert tekken.details.get("console") == "psx", f"console word failed: {tekken.details.get('console')}"
os_iso = classifier.classify(tmp / "downloads" / "win11_23h2_x64.iso")
assert os_iso.category.value == "os_image", f"OS iso regressed: {os_iso.category.value}"
ubuntu_iso = classifier.classify(tmp / "downloads" / "ubuntu-24.04-desktop-amd64.iso")
assert ubuntu_iso.category.value == "os_image", f"ubuntu regressed: {ubuntu_iso.category.value}"
print("[OK ] Disc disambiguation: (USA)/PSX hints -> roms; win11/ubuntu ISOs stay os_image")

# ---------- Zipped ROMs ----------
import zipfile as _zf
zip_cases = [
    ("Super Mario Bros..zip", {"Super Mario Bros..nes"}, "game_rom", "nes"),
    ("Secret of Mana.zip", {"Secret of Mana.sfc", "readme.txt"}, "game_rom", "snes"),
    ("Pokemon Emerald (U).zip", {"Pokemon Emerald.gba"}, "game_rom", "gba"),
    ("3ds homebrew pack.zip", {"homebrew.3dsx", "icon.png"}, "homebrew", "3ds"),
]
for zname, members, want_cat, want_console in zip_cases:
    zp = tmp / "downloads" / zname
    with _zf.ZipFile(zp, "w") as zf:
        for m in members:
            zf.writestr(m, b"\x00" * 16)
    cls = classifier.classify(zp)
    assert cls.category.value == want_cat and cls.details.get("console") == want_console, \
        f"{zname}: {cls.category.value}/{cls.details.get('console')}"
    assert cls.suggested_location == f"/mnt/user/data/{ 'roms' if want_cat=='game_rom' else 'homebrew' }/{want_console}/", \
        f"{zname}: dest={cls.suggested_location}"

# Non-ROM zip stays an archive
plain_zip = tmp / "downloads" / "documents_backup.zip"
with _zf.ZipFile(plain_zip, "w") as zf:
    zf.writestr("notes.txt", "hello")
    zf.writestr("photo.jpg", b"\xff\xd8")
plain = classifier.classify(plain_zip)
assert plain.category.value == "archive", f"plain zip regressed: {plain.category.value}"

# Corrupt zip degrades to archive instead of crashing
bad_zip = tmp / "downloads" / "corrupt.zip"
bad_zip.write_bytes(b"PK\x03\x04garbage")
broken = classifier.classify(bad_zip)
assert broken.category.value == "archive", f"corrupt zip: {broken.category.value}"
print("[OK ] Zipped ROMs: nes/sfc/gba zips + 3dsx pack routed by contents; plain/corrupt zips stay archives")

# ---------- Folder-name hints ----------
folder_cases = [
    # zip with unidentifiable contents, console named by parent folder
    ("Roms/SNES", "Kirby.zip", {"data.bin"}, "snes"),
    ("Roms/NES Roms", "game.zip", {"rom.bin"}, "nes"),
    ("Consoles/Sony PSP", "collection.zip", {"game.iso"}, "psp"),
    # extension-less flash-cart style dump
    ("Roms/Genesis", "mystery", None, "genesis"),
    # grandparent hint (two levels up)
    ("Handhelds/GameBoy Advance", "pack.zip", {"dump.bin"}, "gba"),
]
for sub, fname, members, want_console in folder_cases:
    d = tmp / "downloads" / sub
    d.mkdir(parents=True, exist_ok=True)
    fp = d / fname
    if members is None:
        fp.write_bytes(b"\x00" * 16)
    else:
        with _zf.ZipFile(fp, "w") as zf:
            for m in members:
                zf.writestr(m, b"\x00" * 16)
    cls = classifier.classify(fp)
    assert cls.category.value == "game_rom" and cls.details.get("console") == want_console, \
        f"{sub}/{fname}: {cls.category.value}/{cls.details.get('console')}"
    assert cls.suggested_location == f"/mnt/user/data/roms/{want_console}/"

# Control: same zip shape in a non-console folder stays an archive
neutral = tmp / "downloads" / "misc stuff"
neutral.mkdir(parents=True, exist_ok=True)
nz = neutral / "pack.zip"
with _zf.ZipFile(nz, "w") as zf:
    zf.writestr("rom.bin", b"\x00")
nc = classifier.classify(nz)
assert nc.category.value == "archive", f"neutral folder regressed: {nc.category.value}"
print("[OK ] Folder hints: SNES/NES/PSP/Genesis/GBA folders identify ambiguous zips; neutral folders don't")

print(f"\n{'ALL CHECKS PASSED' if fails == 0 else f'{fails} CHECKS FAILED'}")
sys.exit(1 if fails else 0)
