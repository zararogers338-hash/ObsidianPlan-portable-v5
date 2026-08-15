import { Schema } from "effect"

// OBSIDIAN 统一后端注册表 schema (obsidian.backends.jsonc)

export const BackendModel = Schema.Struct({
  id: Schema.String, // 模型 ID (API 侧)
  name: Schema.optionalWith(Schema.String, { default: () => "" }), // 展示名
  context: Schema.optionalWith(Schema.Number, { default: () => 0 }), // 上下文上限
  toolCall: Schema.optionalWith(Schema.Boolean, { default: () => true }),
  reasoning: Schema.optionalWith(Schema.Boolean, { default: () => false }),
})
export type BackendModel = Schema.Schema.Type<typeof BackendModel>

export const BackendConfig = Schema.Struct({
  // type 决定翻译策略
  type: Schema.Literals(["anthropic", "openai-compatible"]),
  // 内置 SDK 直连 (anthropic) 或 openai-compatible 时必填 endpoint
  endpoint: Schema.optionalWith(Schema.String, { default: () => "" }),
  // 支持 {env:VAR} 引用环境变量, 或字面值
  apiKey: Schema.optionalWith(Schema.String, { default: () => "" }),
  // 自定义请求头 (企业网关场景)
  headers: Schema.optionalWith(Schema.Record(Schema.String, Schema.String), { default: () => ({}) }),
  // 模型白名单: 字符串数组 (= 模型 id) 或完整配置对象
  models: Schema.optionalWith(Schema.Array(Schema.Union([Schema.String, BackendModel])), { default: () => [] }),
  npm: Schema.optionalWith(Schema.String, { default: () => "" }), // 覆盖 provider npm 包 (高级)
})
export type BackendConfig = Schema.Schema.Type<typeof BackendConfig>

export const BackendsFile = Schema.Struct({
  $schema: Schema.optionalWith(Schema.String, { default: () => "" }),
  default: Schema.optionalWith(Schema.String, { default: () => "" }), // 默认后端名
  backends: Schema.Record(Schema.String, BackendConfig),
})
export type BackendsFile = Schema.Schema.Type<typeof BackendsFile>

// {env:VAR} 引用解析: 返回 { kind: "env", var } 或 { kind: "literal", value }
export function resolveSecret(value: string): { kind: "env" | "literal"; value: string } {
  const m = value.match(/^\{env:([A-Z0-9_]+)\}$/i)
  if (m) return { kind: "env", var: m[1] }
  return { kind: "literal", value }
}
