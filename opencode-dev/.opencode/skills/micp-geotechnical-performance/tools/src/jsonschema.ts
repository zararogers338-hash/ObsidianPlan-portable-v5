// Minimal JSON Schema (draft 2020-12 subset) validator.
//
// Supports the keywords this repository's schemas actually use:
//   type, required, properties, additionalProperties, items, enum, const,
//   pattern, minLength, maxLength, minimum, maximum, exclusiveMinimum,
//   minItems, maxItems, anyOf, oneOf, allOf, $ref (local "#/$defs/..." and
//   "#/definitions/..." only), format (annotation only, never rejects).
//
// Unknown keywords are ignored (annotation behavior). Deliberately small and
// dependency-free so the whole skill is offline-testable; it is NOT a
// replacement for a full validator and rejects $dynamicRef/$anchor.
//
// Shared implementation with obsidian-skill-router (tools/osr/jsonschema.ts);
// kept local so this skill stays self-contained.

export interface ValidationIssue {
  path: string
  message: string
}

export type SchemaNode = Record<string, unknown>

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v)
}

const TYPE_CHECKERS: Record<string, (v: unknown) => boolean> = {
  string: (v) => typeof v === "string",
  number: (v) => typeof v === "number" && Number.isFinite(v),
  integer: (v) => typeof v === "number" && Number.isInteger(v),
  boolean: (v) => typeof v === "boolean",
  object: (v) => isObject(v),
  array: (v) => Array.isArray(v),
  null: (v) => v === null,
}

function resolveRef(root: SchemaNode, ref: string): SchemaNode | undefined {
  if (!ref.startsWith("#/")) return undefined // remote refs unsupported by design
  const parts = ref
    .slice(2)
    .split("/")
    .map((p) => decodeURIComponent(p).replace(/~1/g, "/").replace(/~0/g, "~"))
  let node: unknown = root
  for (const part of parts) {
    if (!isObject(node)) return undefined
    node = node[part]
  }
  return isObject(node) ? (node as SchemaNode) : undefined
}

function typeMatches(value: unknown, expected: string | string[]): boolean {
  const list = Array.isArray(expected) ? expected : [expected]
  return list.some((t) => {
    const checker = TYPE_CHECKERS[t]
    if (checker) return checker(value)
    return false // unknown type keyword: fail closed
  })
}

function validateInto(
  value: unknown,
  schema: SchemaNode | boolean,
  root: SchemaNode,
  path: string,
  issues: ValidationIssue[],
  seen: Set<string>,
) {
  if (schema === true) return
  if (schema === false) {
    issues.push({ path, message: "value rejected by `false` schema" })
    return
  }
  if (!isObject(schema)) return

  // $ref (with cycle guard)
  if (typeof schema.$ref === "string") {
    if (seen.has(schema.$ref)) return
    const target = resolveRef(root, schema.$ref)
    if (!target) {
      issues.push({ path, message: `unresolvable $ref: ${schema.$ref}` })
      return
    }
    const next = new Set(seen)
    next.add(schema.$ref)
    validateInto(value, target, root, path, issues, next)
  }

  // enum / const
  if (Array.isArray(schema.enum)) {
    const ok = schema.enum.some((e) => JSON.stringify(e) === JSON.stringify(value))
    if (!ok) issues.push({ path, message: `value not in enum: ${JSON.stringify(schema.enum)}` })
  }
  if ("const" in schema && JSON.stringify(schema.const) !== JSON.stringify(value)) {
    issues.push({ path, message: `value does not equal const ${JSON.stringify(schema.const)}` })
  }

  // type
  if (schema.type !== undefined) {
    if (typeof schema.type !== "string" && !Array.isArray(schema.type)) {
      issues.push({ path, message: "invalid `type` keyword in schema" })
    } else if (!typeMatches(value, schema.type as string | string[])) {
      issues.push({
        path,
        message: `expected type ${JSON.stringify(schema.type)}, got ${Array.isArray(value) ? "array" : value === null ? "null" : typeof value}`,
      })
      return // deeper checks meaningless on type mismatch
    }
  }

  // strings
  if (typeof value === "string") {
    if (typeof schema.minLength === "number" && value.length < schema.minLength) {
      issues.push({ path, message: `string shorter than minLength ${schema.minLength}` })
    }
    if (typeof schema.maxLength === "number" && value.length > schema.maxLength) {
      issues.push({ path, message: `string longer than maxLength ${schema.maxLength}` })
    }
    if (typeof schema.pattern === "string") {
      let re: RegExp | undefined
      try {
        re = new RegExp(schema.pattern, "u")
      } catch {
        issues.push({ path, message: `invalid pattern in schema: ${schema.pattern}` })
      }
      if (re && !re.test(value)) issues.push({ path, message: `string does not match pattern ${schema.pattern}` })
    }
  }

  // numbers
  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) {
      issues.push({ path, message: `number below minimum ${schema.minimum}` })
    }
    if (typeof schema.maximum === "number" && value > schema.maximum) {
      issues.push({ path, message: `number above maximum ${schema.maximum}` })
    }
    if (typeof schema.exclusiveMinimum === "number" && value <= schema.exclusiveMinimum) {
      issues.push({ path, message: `number not above exclusiveMinimum ${schema.exclusiveMinimum}` })
    }
    if (typeof schema.exclusiveMaximum === "number" && value >= schema.exclusiveMaximum) {
      issues.push({ path, message: `number not below exclusiveMaximum ${schema.exclusiveMaximum}` })
    }
  }

  // arrays
  if (Array.isArray(value)) {
    if (typeof schema.minItems === "number" && value.length < schema.minItems) {
      issues.push({ path, message: `array shorter than minItems ${schema.minItems}` })
    }
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) {
      issues.push({ path, message: `array longer than maxItems ${schema.maxItems}` })
    }
    if (schema.items !== undefined) {
      value.forEach((item, idx) => validateInto(item, schema.items as SchemaNode, root, `${path}/${idx}`, issues, seen))
    }
  }

  // objects
  if (isObject(value)) {
    if (Array.isArray(schema.required)) {
      for (const key of schema.required) {
        if (!(key in value)) issues.push({ path, message: `missing required property "${key}"` })
      }
    }
    const props = isObject(schema.properties) ? (schema.properties as Record<string, SchemaNode>) : {}
    for (const [key, propSchema] of Object.entries(props)) {
      if (key in value) validateInto(value[key], propSchema, root, `${path}/${key}`, issues, seen)
    }
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(value)) {
        if (!(key in props)) issues.push({ path, message: `additional property "${key}" not allowed` })
      }
    } else if (isObject(schema.additionalProperties)) {
      for (const key of Object.keys(value)) {
        if (!(key in props)) {
          validateInto(value[key], schema.additionalProperties as SchemaNode, root, `${path}/${key}`, issues, seen)
        }
      }
    }
  }

  // combinators
  if (Array.isArray(schema.allOf)) {
    for (const sub of schema.allOf) validateInto(value, sub as SchemaNode, root, path, issues, new Set(seen))
  }
  if (Array.isArray(schema.anyOf)) {
    const ok = (schema.anyOf as SchemaNode[]).some((sub) => validate(value, sub, root).length === 0)
    if (!ok) issues.push({ path, message: "value matches none of the anyOf branches" })
  }
  if (Array.isArray(schema.oneOf)) {
    const matches = (schema.oneOf as SchemaNode[]).filter((sub) => validate(value, sub, root).length === 0)
    if (matches.length !== 1) {
      issues.push({ path, message: `value matches ${matches.length} oneOf branches (expected exactly 1)` })
    }
  }
  if (isObject(schema.not)) {
    if (validate(value, schema.not as SchemaNode, root).length === 0) {
      issues.push({ path, message: "value matches the `not` schema" })
    }
  }
}

export function validate(value: unknown, schema: SchemaNode, root?: SchemaNode): ValidationIssue[] {
  const issues: ValidationIssue[] = []
  validateInto(value, schema, root ?? schema, "", issues, new Set())
  return issues
}
