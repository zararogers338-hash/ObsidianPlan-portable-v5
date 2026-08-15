/**
 * Obsidian Mission Lock — typed error codes.
 *
 * Machine-parseable, human-readable error taxonomy for the skill.
 * Every failure path in the skill returns one of these codes so the
 * Obsidian controller can route programmatically.
 */

export const ERROR_CODES = [
  "OML-E1001", // input schema validation failed
  "OML-E1002", // evidence reference not verifiable
  "OML-E1003", // unit / scale / temporal inconsistency
  "OML-E1004", // required tool unavailable
  "OML-E1005", // insufficient permission
  "OML-E1006", // downstream capability missing
  "OML-E1007", // human approval not completed
  "OML-E1008", // output failed self-check
  "OML-E1009", // context or file corrupted
  "OML-E1010", // contract version incompatible
] as const

export type ErrorCode = (typeof ERROR_CODES)[number]

const DESCRIPTIONS: Record<ErrorCode, { en: string; zh: string; retryable: boolean }> = {
  "OML-E1001": { en: "Input failed schema validation", zh: "输入未通过 schema 校验", retryable: false },
  "OML-E1002": { en: "Evidence reference could not be verified", zh: "证据引用不可核验", retryable: false },
  "OML-E1003": { en: "Unit, scale, or temporal range inconsistency", zh: "单位/尺度/时间范围不一致", retryable: false },
  "OML-E1004": { en: "A required tool is unavailable", zh: "依赖工具不可用", retryable: true },
  "OML-E1005": { en: "Insufficient permission for the requested action", zh: "权限不足", retryable: false },
  "OML-E1006": { en: "A required downstream skill/capability is missing", zh: "下游能力缺失", retryable: false },
  "OML-E1007": { en: "Required human approval gate has not been completed", zh: "人工审批未完成", retryable: true },
  "OML-E1008": { en: "Generated output failed the skill's self-check", zh: "结果未通过自检", retryable: false },
  "OML-E1009": { en: "Context or referenced file is corrupted or unreadable", zh: "上下文或文件损坏", retryable: false },
  "OML-E1010": { en: "Contract version is incompatible and no migration exists", zh: "合同版本不兼容且无迁移路径", retryable: false },
}

export class MissionLockError extends Error {
  readonly code: ErrorCode
  readonly retryable: boolean
  readonly details: Record<string, unknown>

  constructor(code: ErrorCode, message: string, details: Record<string, unknown> = {}) {
    super(`[${code}] ${DESCRIPTIONS[code].zh} — ${message}`)
    this.name = "MissionLockError"
    this.code = code
    this.retryable = DESCRIPTIONS[code].retryable
    this.details = details
  }

  /** Machine-readable serialization for controller consumption. */
  toJSON() {
    return {
      code: this.code,
      name: this.name,
      message: this.message,
      retryable: this.retryable,
      details: this.details,
    }
  }
}

export function describeError(code: ErrorCode): { en: string; zh: string; retryable: boolean } {
  return DESCRIPTIONS[code]
}
