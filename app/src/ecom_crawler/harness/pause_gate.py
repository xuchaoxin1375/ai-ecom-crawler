"""Install the per-workspace OpenCode pause-gate plugin.

The plugin reads ``control/pause.json`` on every permission evaluation.  When
the flag is true it escalates an otherwise allowed tool action to ``ask`` so
the BuildService can hold the request until resume.  An unreadable control
file is treated as paused (fail closed).
"""

from __future__ import annotations

from pathlib import Path

PLUGIN_ID = "pause-gate"

PACKAGE_JSON = """\
{
  "name": "pause-gate",
  "private": true,
  "type": "module",
  "exports": { ".": "./index.js" }
}
"""

PLUGIN_SOURCE = """\
import { Plugin } from "@opencode/plugin"
import { appendFileSync, readFileSync } from "node:fs"
import { resolve } from "node:path"

const controlPath = (ctx) => resolve(ctx.location.directory, "..", "control", "pause.json")
const logPath = (ctx) => resolve(ctx.location.directory, "..", "control", "pause-gate.log")

const log = (ctx, text) => {
  try {
    appendFileSync(logPath(ctx), `${new Date().toISOString()} ${text}\\n`)
  } catch {
    // Logging must never change the permission decision.
  }
}

export default Plugin.define({
  id: "pause-gate",
  async setup(ctx) {
    log(ctx, "setup " + ctx.location.directory)
    await ctx.permission.hook("evaluate", async (event) => {
      let paused = true
      try {
        paused = JSON.parse(readFileSync(controlPath(ctx), "utf8"))?.paused === true
      } catch {
        paused = true
      }
      const previous = event.effect
      if (paused) {
        event.effect = "ask"
        event.message = "build paused; permission held by pause-gate"
      }
      log(ctx, `${event.action} ${previous} -> ${event.effect}`)
    })
  },
})
"""


def install_pause_gate(work_dir: str | Path) -> Path:
    """Write the plugin package into a build workspace and return its path."""
    plugin_dir = Path(work_dir) / ".opencode" / "plugins" / PLUGIN_ID
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "package.json").write_text(PACKAGE_JSON, encoding="utf-8")
    (plugin_dir / "index.js").write_text(PLUGIN_SOURCE, encoding="utf-8")
    return plugin_dir
