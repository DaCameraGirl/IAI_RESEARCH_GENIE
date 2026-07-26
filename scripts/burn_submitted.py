from pathlib import Path

p = Path("26052_Rechargeable_Blender_Offset_Blades/known_art/known_citations.csv")
content = p.read_text(encoding="utf-8")
to_add = [
    "US7217028",
    "US20050207270",
    "US5323973",
    "CN206565826U",
    "CN206565828U",
    "CN206565826",
    "CN206565828"
]
added = 0
for pat in to_add:
    if pat not in content:
        content += f'"{pat}","Patent","Submitted Duplicate"\n'
        added += 1

p.write_text(content, encoding="utf-8")
print(f"Added {added} submitted duplicate patents to 26052 known_citations.csv")
