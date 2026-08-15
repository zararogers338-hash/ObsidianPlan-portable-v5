// OSR (obsidian-skill-router) error code taxonomy.
//
// Every machine-facing failure in this skill carries one of these codes.
// Codes are stable within a major version: new codes may be added in minor
// releases, existing codes are never renumbered or removed.

export const ERROR_CODES = [
  "OSR-E001", // INPUT_SCHEMA_INVALID — input failed schemas/input.schema.json
  "OSR-E002", // EVIDENCE_UNVERIFIABLE — evidence/data refs missing, unreadable or corrupted
  "OSR-E003", // UNIT_INCOMPATIBLE — unit/scale mismatch across chained skill contracts
  "OSR-E004", // DEPENDENCY_UNAVAILABLE — required local dependency or tool unavailable
  "OSR-E005", // PERMISSION_INSUFFICIENT — policy engine denies a required action
  "OSR-E006", // CAPABILITY_GAP — no registered skill covers a required capability
  "OSR-E007", // APPROVAL_PENDING — human approval required but not granted
  "OSR-E008", // SELF_CHECK_FAILED — router output failed its own contract self-check
  "OSR-E009", // CONTEXT_CORRUPTED — context/refs/decision log malformed or unreadable
  "OSR-E010", // BUDGET_EXCEEDED — token/cost/time/retry budget would be exceeded
  "OSR-E011", // DEPTH_EXCEEDED — call-graph depth or total call budget exceeded
  "OSR-E012", // DUPLICATE_INVOCATION — exact repeated invocation of the same skill
  "OSR-E013", // CONFLICT_UNRESOLVED — outputs of executed skills conflict and arbitration failed
  "OSR-E014", // REGISTRY_CORRUPTED — skill registry files unreadable or fail contract checks
  "OSR-E015", // CONTRACT_MISMATCH — selected skill's input/output contract incompatible with request
  "OSR-E016", // VERSION_INCOMPATIBLE — unsupported skill_version/controller_version
  "OSR-E017", // INTERNAL — unexpected implementation failure
] as const

export type ErrorCode = (typeof ERROR_CODES)[number]

export type ErrorClass = "input" | "dependency" | "policy" | "capability" | "state" | "internal"

export interface ErrorSpec {
  code: ErrorCode
  class: ErrorClass
  retryable: boolean
  human: string // human-readable summary, zh
}

export const ERROR_SPECS: Record<ErrorCode, ErrorSpec> = {
  "OSR-E001": { code: "OSR-E001", class: "input", retryable: false, human: "输入未通过 schemas/input.schema.json 校验" },
  "OSR-E002": { code: "OSR-E002", class: "input", retryable: false, human: "证据或数据引用缺失、不可读或已损坏" },
  "OSR-E003": { code: "OSR-E003", class: "input", retryable: false, human: "链式传递的输出与下游技能声明的单位/量纲不一致" },
  "OSR-E004": { code: "OSR-E004", class: "dependency", retryable: true, human: "所需本地依赖或工具不可用" },
  "OSR-E005": { code: "OSR-E005", class: "policy", retryable: false, human: "权限策略拒绝该操作" },
  "OSR-E006": { code: "OSR-E006", class: "capability", retryable: false, human: "注册表中无覆盖所需能力的技能" },
  "OSR-E007": { code: "OSR-E007", class: "policy", retryable: false, human: "需要人工批准但当前未获批准" },
  "OSR-E008": { code: "OSR-E008", class: "internal", retryable: false, human: "路由结果未通过自身输出契约自检" },
  "OSR-E009": { code: "OSR-E009", class: "state", retryable: false, human: "上下文、引用或决策日志损坏、不可解析" },
  "OSR-E010": { code: "OSR-E010", class: "policy", retryable: false, human: "预算（token/成本/时间/重试）将超限" },
  "OSR-E011": { code: "OSR-E011", class: "policy", retryable: false, human: "调用图深度或总调用数将超限" },
  "OSR-E012": { code: "OSR-E012", class: "input", retryable: false, human: "检测到对同一技能的精确重复调用" },
  "OSR-E013": { code: "OSR-E013", class: "state", retryable: false, human: "已执行技能输出冲突且仲裁失败" },
  "OSR-E014": { code: "OSR-E014", class: "dependency", retryable: false, human: "技能注册表文件不可读或未通过契约检查" },
  "OSR-E015": { code: "OSR-E015", class: "capability", retryable: false, human: "所选技能输入/输出契约与请求不兼容" },
  "OSR-E016": { code: "OSR-E016", class: "input", retryable: false, human: "skill_version 或 controller_version 不在支持范围内" },
  "OSR-E017": { code: "OSR-E017", class: "internal", retryable: true, human: "实现内部错误" },
}

export interface OsError {
  code: ErrorCode
  message: string
  details?: Record<string, unknown>
  retryable: boolean
}

export function makeError(code: ErrorCode, message: string, details?: Record<string, unknown>): OsError {
  return { code, message, details, retryable: ERROR_SPECS[code].retryable }
}
