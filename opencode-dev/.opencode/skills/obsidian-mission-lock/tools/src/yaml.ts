/**
 * Minimal YAML subset parser for evals/cases.yaml.
 *
 * Supports exactly what the cases file needs:
 *   - comments (# ...)
 *   - block mappings (key: value)
 *   - sequences of block mappings (items introduced by "- ")
 *   - scalars: strings (bare/quoted), booleans, numbers
 *   - inline arrays "[a, b, c]"
 *
 * Structure is validated eagerly so a typo cannot silently change eval
 * semantics. Offline, deterministic, no deps.
 */

export function parseYaml(text: string): unknown {
  const lines = text.split(/\r?\n/)
  const root: Record<string, unknown> = {}
  // Stack of { indent, container }. The `indent` is the indent of the line
  // that OPENED the container: keys/items with indent > opened-indent belong
  // to it; a line with indent <= opened-indent closes it.
  // For a sequence, the list's opened-indent is the KEY line's indent (e.g.
  // the "cases:" line), so every "- " deeper than it stays inside the list.
  const stack: { indent: number; container: Record<string, unknown> | unknown[] }[] = [
    { indent: -1, container: root },
  ]

  function indentOf(line: string): number {
    return line.match(/^ */)![0].length
  }

  let i = 0
  while (i < lines.length) {
    const raw = lines[i]
    i++
    const trimmed = raw.trim()
    if (trimmed === "" || trimmed.startsWith("#")) continue

    const indent = indentOf(raw)

    // Close containers opened at >= this indent
    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) stack.pop()

    const parent = stack[stack.length - 1]

    if (trimmed.startsWith("- ")) {
      if (!Array.isArray(parent.container)) {
        throw new Error(`parseYaml: line ${i}: sequence item "- " not inside a list container`)
      }
      const rest = trimmed.slice(2)
      const colon = rest.indexOf(":")
      if (colon === -1) {
        parent.container.push(parseScalar(rest))
        continue
      }
      const key = rest.slice(0, colon).trim()
      const value = rest.slice(colon + 1).trim()
      const item: Record<string, unknown> = {}
      parent.container.push(item)
      // The item's own keys (if any) appear at this same indent; its nested
      // blocks appear deeper. Push the item so deeper keys write into it.
      stack.push({ indent, container: item })
      if (value !== "") item[key] = parseScalar(value)
      continue
    }

    // Mapping key: value
    const colon = trimmed.indexOf(":")
    if (colon === -1) throw new Error(`parseYaml: line ${i}: expected "key: value", got "${trimmed}"`)
    const key = trimmed.slice(0, colon).trim()
    const value = trimmed.slice(colon + 1).trim()
    if (!(parent.container instanceof Object) || Array.isArray(parent.container)) {
      throw new Error(`parseYaml: line ${i}: mapping key "${key}" outside a mapping container`)
    }
    const obj = parent.container as Record<string, unknown>

    if (value === "") {
      // Empty value → peek next meaningful line to decide: empty scalar,
      // list, or nested mapping.
      let j = i
      while (j < lines.length && (lines[j].trim() === "" || lines[j].trim().startsWith("#"))) j++
      if (j >= lines.length) {
        obj[key] = ""
        continue
      }
      const nextIndent = indentOf(lines[j])
      const nextTrimmed = lines[j].trim()
      if (nextIndent <= indent) {
        obj[key] = "" // empty scalar
        continue
      }
      if (nextTrimmed.startsWith("- ")) {
        const list: unknown[] = []
        obj[key] = list
        stack.push({ indent, container: list })
        i = j
        continue
      }
      const nested: Record<string, unknown> = {}
      obj[key] = nested
      stack.push({ indent, container: nested })
      i = j
      continue
    }

    obj[key] = parseScalar(value)
  }

  return root
}

function parseScalar(s: string): unknown {
  const v = s.trim()
  if (v === "") return ""
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
    return v.slice(1, -1)
  }
  if (v === "true") return true
  if (v === "false") return false
  if (/^-?\d+$/.test(v)) return parseInt(v, 10)
  if (/^-?\d+\.\d+$/.test(v)) return parseFloat(v)
  if (v.startsWith("[") && v.endsWith("]")) {
    const inner = v.slice(1, -1).trim()
    if (inner === "") return []
    return inner.split(",").map((x) => parseScalar(x.trim()))
  }
  const hash = v.indexOf(" #")
  return hash === -1 ? v : v.slice(0, hash).trim()
}
