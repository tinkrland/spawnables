#!/usr/bin/env python3
"""turn recipe.json into a movie maker project file.

honest status: the element shape below is a skeleton assembled from how wmm
2012 project files read (wmproject root, media items, a timeline). it has NOT
been verified against a real install, because the pilot's first job is to
replace it with a project file captured from the machine. if movie maker
refuses it, that is the pilot working: the fixture failed loudly instead of
quietly passing.
"""
import json
import pathlib

here = pathlib.Path(__file__).resolve().parent
recipe = json.loads((here / "input" / "recipe.json").read_text())

items = "".join(
    f'<MediaItem FilePath="{c["file"]}" Duration="{c["seconds"]}"/>'
    for c in recipe["clips"])

project = f'''<?xml version="1.0" encoding="utf-8"?>
<wmproject version="1.0" name="{recipe["output"]}">
  <MediaItems>{items}</MediaItems>
  <Timeline>
    <TitleText>{recipe["title_text"]}</TitleText>
    <AudioTrack file="{recipe["audio"]}"/>
    <Target>{recipe["target"]}</Target>
  </Timeline>
</wmproject>
'''
(here / ".build" / "cut.wlmp").parent.mkdir(parents=True, exist_ok=True)
(here / ".build" / "cut.wlmp").write_text(project, encoding="utf-8")
print(f"wrote .build/cut.wlmp for {recipe['output']}")
