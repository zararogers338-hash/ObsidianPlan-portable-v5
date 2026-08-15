// MGE (micp-geotechnical-performance) error code taxonomy.
//
// Every machine-facing failure in this skill carries one of these codes.
// Codes are stable within a major version: new codes may be added in minor
// releases, existing codes are never renumbered or removed.

export const ERROR_CODES = [
  "MGE-E101", // INPUT_SCHEMA_INVALID — input failed schemas/input.schema.json
  "MGE-E201", // EVIDENCE_UNVERIFIABLE — evidence/data refs missing, unreadable or corrupted
  "MGE-E202", // REQUIRED_TEST_DATA_MISSING — request needs strength/permeability/durability but no samples
  "MGE-E203", // UNIT_INCOMPATIBLE — unit/scale mismatch that cannot be converted
  "MGE-E301", // DEPENDENCY_UNAVAILABLE — required local dependency or runtime unavailable
  "MGE-E302", // NUMERIC_VALIDATION_FAILED — null/non-finite/range/dimension/precision checks failed
  "MGE-E303", // INSUFFICIENT_DATA — too few data points for fitting/statistics
  "MGE-E304", // SPECIMEN_INCOMPARABLE — specimens differ too much in size/density/stress path
  "MGE-E305", // PARSE_FAILED — input format could not be parsed
  "MGE-E401", // PERMISSION_INSUFFICIENT — policy engine denies a required action
  "MGE-E501", // CAPABILITY_GAP — a required downstream capability is missing
  "MGE-E601", // CONTEXT_CORRUPTED — context/refs/data files malformed or unreadable
  "MGE-E701", // APPROVAL_PENDING — human approval required but not granted
  "MGE-E801", // SELF_CHECK_FAILED — output failed its own contract self-check
  "MGE-E802", // INTERNAL — unexpected implementation failure
  "MGE-E803", // VERSION_INCOMPATIBLE — unsupported skill_version/controller_version, no migration
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
  "MGE-E101": { code: "MGE-E101", class: "input", retryable: false, human: "输入未通过 schemas/input.schema.json 校验" },
  "MGE-E201": { code: "MGE-E201", class: "input", retryable: false, human: "证据或数据引用缺失、不可读或已损坏" },
  "MGE-E202": { code: "MGE-E202", class: "input", retryable: false, human: "请求要求强度/渗透/耐久评价但未提供 samples 试验数据" },
  "MGE-E203": { code: "MGE-E203", class: "input", retryable: false, human: "单位/量纲不一致且无法换算" },
  "MGE-E301": { code: "MGE-E301", class: "dependency", retryable: true, human: "所需本地依赖或运行时不可用" },
  "MGE-E302": { code: "MGE-E302", class: "input", retryable: false, human: "数值校验失败(空值/非有限值/范围/维度/精度)" },
  "MGE-E303": { code: "MGE-E303", class: "input", retryable: false, human: "数据点不足,无法完成拟合或统计" },
  "MGE-E304": { code: "MGE-E304", class: "input", retryable: false, human: "试样条件差异过大,不可直接比较" },
  "MGE-E305": { code: "MGE-E305", class: "input", retryable: false, human: "输入格式无法解析" },
  "MGE-E401": { code: "MGE-E401", class: "policy", retryable: false, human: "权限策略拒绝该操作" },
  "MGE-E501": { code: "MGE-E501", class: "capability", retryable: false, human: "需要下游能力但未提供(返回 NEED_ADDITIONAL_SKILL)" },
  "MGE-E601": { code: "MGE-E601", class: "state", retryable: false, human: "上下文、引用或数据文件损坏、不可解析" },
  "MGE-E701": { code: "MGE-E701", class: "policy", retryable: false, human: "需要人工批准但当前未获批准" },
  "MGE-E801": { code: "MGE-E801", class: "internal", retryable: false, human: "结果未通过自身输出契约自检" },
  "MGE-E802": { code: "MGE-E802", class: "internal", retryable: true, human: "实现内部错误" },
  "MGE-E803": { code: "MGE-E803", class: "state", retryable: false, human: "skill/controller 版本不受支持且无迁移器" },
}

export interface MgeError {
  code: ErrorCode
  message: string
  details?: Record<string, unknown>
  retryable: boolean
}

export function makeError(code: ErrorCode, message: string, details?: Record<string, unknown>): MgeError {
  return { code, message, details, retryable: ERROR_SPECS[code].retryable }
}
