// Minimal YAML-subset parser, sufficient for SKILL.md frontmatter and this
// repository's skill.yaml files: nested block mappings, block sequences,
// flow sequences ("[a, b]"), quoted/plain scalars, comments.
//
// Deliberately NOT a full YAML implementation (no anchors, no block scalars,
// no flow mappings). Unsupported constructs raise YAMLParseError so callers
// fail loudly instead of silently misreading the file.

export class YAMLParseError extends Error {
  constructor(
    message: string,
    readonly line: number,
  ) {
    super(`YAML parse error at line ${line}: ${message}`)
    this.name = "YAMLParseError"
  }
}

type Scalar = string | number | boolean | null

function parseScalar(raw: string, line: number): unknown {
  const s = raw.trim()
  if (s === "" || s === "~" || /^null$/i.test(s)) return null
  if (/^true$/i.test(s)) return true
  if (/^false$/i.test(s)) return false
  if (/^-?\d+$/.test(s)) return Number.parseInt(s, 10)
  if (/^-?\d*\.\d+([eE][+-]?\d+)?$/.test(s)) return Number.parseFloat(s)
  if (s.startsWith('"') && s.endsWith('"') && s.length >= 2) {
    return s.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\")
  }
  if (s.startsWith("'") && s.endsWith("'") && s.length >= 2) return s.slice(1, -1).replace(/''/g, "'")
  if (s.startsWith("[") && s.endsWith("]")) {
    const inner = s.slice(1, -1).trim()
    if (inner === "") return [] as unknown[]
    return inner.split(",").map((p) => parseScalar(p, line))
  }
  if (s === "{}" || s === "{ }") return {} as Record<string, unknown>
  if (s.startsWith("{")) throw new YAMLParseError(`flow mappings are not supported: ${s}`, line)
  return s
}

function stripComment(line: string): string {
  let inSingle = false
  let inDouble = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (c === "'" && !inDouble) inSingle = !inSingle
    else if (c === '"' && !inSingle) inDouble = !inDouble
    else if (c === "#" && !inSingle && !inDouble && (i === 0 || line[i - 1] === " ")) return line.slice(0, i)
  }
  return line
}

interface Frame {
  indent: number
  container: Record<string, unknown> | unknown[]
  parent: Record<string, unknown> | unknown[] | null
  parentKey: string | number | null
  /** when set, this frame is a block scalar collector (| or >- styles) */
  blockScalar?: { style: "literal" | "folded"; collected: string[]; baseIndent: number }
}

export function parseYAML(text: string): Record<string, unknown> {
  const lines = text.replace(/\r\n/g, "\n").split("\n")
  const root: Record<string, unknown> = {}
  const stack: Frame[] = [{ indent: -1, container: root, parent: null, parentKey: null }]

  const assign = (map: Record<string, unknown>, content: string, lineNo: number, indent: number) => {
    const m = /^([^:]+):\s*(.*)$/.exec(content)
    if (!m) throw new YAMLParseError(`expected "key: value", got: ${content}`, lineNo)
    const key = m[1]?.trim() ?? ""
    if (key === "") throw new YAMLParseError("empty key", lineNo)
    const rest = m[2] ?? ""
    if (rest.trim() !== "") {
      // Block scalar indicator: "key: >-", "key: |", "key: >", "key: |2"
      if (/^[|>][-+]?\d*$/.test(rest.trim())) {
        const style = rest.trim().startsWith("|") ? "literal" : "folded"
        const child: Record<string, unknown> = {}
        map[key] = ""
        stack.push({ indent, container: child, parent: map, parentKey: key, blockScalar: { style, collected: [], baseIndent: -1 } })
        return
      }
      map[key] = parseScalar(rest, lineNo)
      return
    }
    const child: Record<string, unknown> = {}
    map[key] = child
    stack.push({ indent, container: child, parent: map, parentKey: key })
  }

  for (let i = 0; i < lines.length; i++) {
    const lineNo = i + 1
    const rawLine = lines[i]
    if (rawLine === undefined) continue
    if (rawLine.includes("\t")) throw new YAMLParseError("tab indentation is not supported", lineNo)
    const noComment = stripComment(rawLine)
    const trimmed = noComment.trim()
    if (trimmed === "" || trimmed === "---" || trimmed === "...") continue
    const indent = noComment.length - noComment.trimStart().length

    // Block scalar collector: consume indented lines while top frame collects.
    const topCollector = stack[stack.length - 1]
    if (topCollector?.blockScalar && indent > topCollector.indent) {
      const bs = topCollector.blockScalar
      if (bs.baseIndent < 0) bs.baseIndent = indent
      bs.collected.push(noComment.slice(bs.baseIndent))
      continue
    }
    if (topCollector?.blockScalar) {
      // A less-indented line ends the block scalar; finalize into the parent map.
      finalizeBlockScalar(stack, topCollector)
    }

    while (stack.length > 1 && indent <= (stack[stack.length - 1]?.indent ?? 0)) stack.pop()
    const top = stack[stack.length - 1]
    if (!top) throw new YAMLParseError("internal stack underflow", lineNo)

    if (trimmed === "-" || trimmed.startsWith("- ")) {
      let active = top
      if (!Array.isArray(active.container)) {
        // The parent mapping key we just opened must become a sequence.
        const parentFrame = stack[stack.length - 2]
        if (!parentFrame || Array.isArray(parentFrame.container) || active.parentKey === null) {
          throw new YAMLParseError("sequence item without a parent mapping key", lineNo)
        }
        const seq: unknown[] = []
        ;(parentFrame.container as Record<string, unknown>)[active.parentKey] = seq
        stack[stack.length - 1] = { indent: active.indent, container: seq, parent: parentFrame.container, parentKey: active.parentKey }
        active = stack[stack.length - 1] as Frame
      }
      const seq = active.container as unknown[]
      const itemText = trimmed === "-" ? "" : trimmed.slice(2).trim()
      if (itemText === "") {
        const child: Record<string, unknown> = {}
        seq.push(child)
        stack.push({ indent, container: child, parent: seq, parentKey: seq.length - 1 })
      } else if (/^[^:"'][^:]*:\s*/.test(itemText)) {
        // map entry opening inside a sequence item: "- name: x"
        const child: Record<string, unknown> = {}
        seq.push(child)
        // children of this map use the item's indent for popping purposes
        assign(child, itemText, lineNo, indent + 2)
        stack.push({ indent: indent, container: child, parent: seq, parentKey: seq.length - 1 })
      } else {
        seq.push(parseScalar(itemText, lineNo))
      }
      continue
    }

    if (Array.isArray(top.container)) {
      throw new YAMLParseError(`mapping entry inside sequence: ${trimmed}`, lineNo)
    }
    assign(top.container as Record<string, unknown>, trimmed, lineNo, indent)
  }

  // Finalize any trailing block scalar at end of input.
  const tail = stack[stack.length - 1]
  if (tail?.blockScalar) finalizeBlockScalar(stack, tail)
  return root
}

function finalizeBlockScalar(stack: Frame[], frame: Frame) {
  const bs = frame.blockScalar
  if (!bs) return
  const raw = bs.collected
  let value: string
  if (bs.style === "literal") {
    value = raw.join("\n")
  } else {
    // folded: join non-empty lines with space; blank lines become newlines
    value = raw
      .map((line) => (line.trim() === "" ? "\n" : line.trim()))
      .join(" ")
      .replace(/ \n /g, "\n")
  }
  const trimmed = value.replace(/^\n+|\n+$/g, "").trimEnd()
  if (stack.length >= 2) {
    const parent = stack[stack.length - 2]
    if (parent && !Array.isArray(parent.container) && frame.parentKey !== null) {
      ;(parent.container as Record<string, unknown>)[frame.parentKey] = trimmed
    } else if (parent && Array.isArray(parent.container) && typeof frame.parentKey === "number") {
      parent.container[frame.parentKey] = trimmed
    }
  }
  frame.blockScalar = undefined
  stack.pop()
}

// Minimal YAML emitter for the subset above (used by registry build --write).
export function dumpYAML(value: unknown, indent = 0): string {
  const pad = "  ".repeat(indent)
  if (value === null || value === undefined) return "null"
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  if (typeof value === "string") {
    if (value === "" || /[:#\[\]{}",'&*!|>%@`]|^\s|\s$|^[-?]$/.test(value)) return JSON.stringify(value)
    return value
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]"
    return value
      .map((item) => {
        if (typeof item === "object" && item !== null && !Array.isArray(item)) {
          const entries = Object.entries(item as Record<string, unknown>)
          if (entries.length === 0) return `${pad}- {}`
          const first = entries[0]
          if (!first) return `${pad}- {}`
          const [firstKey, firstVal] = first
          const rest = entries.slice(1)
          const head = `${pad}- ${firstKey}: ${dumpYAML(firstVal, 0)}`
          const tail = rest.map(([k, v]) => `${pad}  ${k}: ${dumpYAML(v, indent + 2)}`).join("\n")
          return tail ? `${head}\n${tail}` : head
        }
        return `${pad}- ${dumpYAML(item, 0)}`
      })
      .join("\n")
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return "{}"
    return entries
      .map(([k, v]) => {
        if (typeof v === "object" && v !== null && !(Array.isArray(v) && v.length === 0)) {
          const rendered = dumpYAML(v, indent + 1)
          return `${pad}${k}:\n${rendered}`
        }
        return `${pad}${k}: ${dumpYAML(v, 0)}`
      })
      .join("\n")
  }
  throw new Error(`cannot dump value of type ${typeof value}`)
}
