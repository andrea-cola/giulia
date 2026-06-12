"""Utility to load a SKILL.md file into an ADK Skill object.

Usage::

    from giulia.agents.services.skill_loader import load_skill
    from google.adk.tools.skill_toolset import SkillToolset

    skill = load_skill(Path(__file__).parent / "skills" / "my-skill")
    skillset = SkillToolset(skills=[skill])
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def load_skill(skill_dir: Path) -> Any:
    """Parse a SKILL.md (with optional YAML front-matter) into an ADK Skill.

    Args:
        skill_dir: directory containing a ``SKILL.md`` file.

    Returns:
        A ``google.adk.tools.skill_toolset.models.Skill`` instance.
    """
    from google.adk.tools.skill_toolset import models

    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", skill_md, re.DOTALL)

    if fm_match:
        import yaml

        fm_raw: dict[str, Any] = yaml.safe_load(fm_match.group(1)) or {}
        instructions = fm_match.group(2).strip()
    else:
        fm_raw = {}
        instructions = skill_md.strip()

    name = fm_raw.get("name", skill_dir.name)
    description = fm_raw.get("description", "")
    if isinstance(description, dict):
        description = " ".join(str(v) for v in description.values())
    description = str(description).strip()

    references: dict[str, str] = {}
    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        for ref_file in refs_dir.glob("*.md"):
            references[ref_file.name] = ref_file.read_text(encoding="utf-8")

    return models.Skill(
        frontmatter=models.Frontmatter(name=name, description=description),
        instructions=instructions,
        resources=models.Resources(references=references),
    )


def load_skillset(skill_dir: Path) -> Any | None:
    """Load a skill and wrap it in a SkillToolset. Returns None if SkillToolset is unavailable."""
    try:
        from google.adk.tools.skill_toolset import SkillToolset

        return SkillToolset(skills=[load_skill(skill_dir)])
    except ImportError:
        return None


def load_skillset_multi(*skill_dirs: Path) -> Any | None:
    """Load multiple skill directories into a single SkillToolset.

    Use this instead of calling load_skillset() multiple times on the same agent.
    Two separate SkillToolset instances on the same agent cause a
    'Duplicate function declaration: list_skills' error from the Gemini API.
    """
    try:
        from google.adk.tools.skill_toolset import SkillToolset

        return SkillToolset(skills=[load_skill(d) for d in skill_dirs])
    except ImportError:
        return None
