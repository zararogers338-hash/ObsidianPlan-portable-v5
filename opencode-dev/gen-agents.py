# -*- coding: utf-8 -*-
"""生成黑曜石 agents 配置: 25 个 skill → subagent agent。
从每个 skill 的 SKILL.md frontmatter 提取 name/description,生成 opencode.json 的 agent 字段。"""
import os, re, json, sys

sys.stdout.reconfigure(encoding="utf-8")

# 使用脚本所在目录作为基准，避免绝对路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(SCRIPT_DIR, ".opencode", "skills")
OUT = os.path.join(SCRIPT_DIR, "obsidian-agents.json")

def read_frontmatter(fp):
    with open(fp, encoding="utf-8", errors="replace") as f:
        content = f.read()
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.S)
    if not m:
        return {}
    data = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" ") and not line.startswith("\t"):
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip().strip('"')
    return data

agents = {}
for d in sorted(os.listdir(SKILLS_DIR)):
    dp = os.path.join(SKILLS_DIR, d)
    sk = os.path.join(dp, "SKILL.md")
    if not os.path.isfile(sk):
        continue
    fm = read_frontmatter(sk)
    name = fm.get("name", d)
    desc = fm.get("description", "")
    if isinstance(desc, str) and len(desc) > 400:
        desc = desc[:400] + "..."
    agents[name] = {
        "mode": "subagent",
        "description": desc,
        "prompt": (
            f"You are the **{name}** subagent in the Obsidian Plan / Panshi research system. "
            "Load and follow your SKILL.md instructions (in .opencode/skills/). "
            "Output structured JSON per your skill's output contract. "
            "You operate under the Panshi Constitution: mark epistemics, check units, "
            "never fabricate data, and route formal conclusions through Red Team / Decision Gate."
        ),
        "hidden": False,
    }

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(agents, f, ensure_ascii=False, indent=2)
print(f"已生成 {len(agents)} 个 agent 定义:")
for name in agents:
    print(f"  - {name}")
print(f"\n输出: {OUT}")
