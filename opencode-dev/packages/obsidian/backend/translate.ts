import { resolveSecret, type BackendsFile, type BackendConfig } from "./schema"

// 翻译器: obsidian.backends.jsonc → opencode 原生 provider 配置 (纯函数, 无副作用)

export type TranslatedProvider = {
  name?: string
  npm?: string
  env?: string[]
  options: {
    apiKey?: string
    baseURL?: string
    [key: string]: unknown
  }
  models?: Record<string, unknown>
}

export type TranslatedConfig = {
  provider?: Record<string, TranslatedProvider>
  model?: string // default backend 对应的默认模型
}

export function translateBackends(file: BackendsFile): TranslatedConfig {
  const result: TranslatedConfig = {}
  const providers: Record<string, TranslatedProvider> = {}

  for (const [name, backend] of Object.entries(file.backends)) {
    const translated = translateBackend(name, backend)
    providers[name] = translated.provider
    if (name === file.default && translated.defaultModel) {
      result.model = `${name}/${translated.defaultModel}`
    }
  }

  if (Object.keys(providers).length > 0) result.provider = providers
  return result
}

function translateBackend(name: string, backend: BackendConfig): { provider: TranslatedProvider; defaultModel?: string } {
  const envVars: string[] = []
  const options: TranslatedProvider["options"] = {}
  const models: Record<string, unknown> = {}

  const secret = resolveSecret(backend.apiKey || "")
  if (secret.kind === "env") {
    envVars.push(secret.var)
  } else if (secret.value) {
    options.apiKey = secret.value
  }

  if (backend.type === "anthropic") {
    // 内置 anthropic SDK 直连
    options.baseURL = backend.endpoint || undefined
  } else {
    // openai-compatible: 默认 @ai-sdk/openai-compatible
    options.baseURL = backend.endpoint || undefined
  }

  if (Object.keys(backend.headers).length > 0) {
    options.headers = { ...backend.headers }
  }

  // 模型白名单: 字符串 → {id: ...}, 完整对象 → 展开能力位/上下文
  let defaultModel: string | undefined
  for (const m of backend.models) {
    if (typeof m === "string") {
      models[m] = { id: m, tool_call: true }
      if (!defaultModel) defaultModel = m
    } else {
      const modelObj: Record<string, unknown> = {
        id: m.id,
        name: m.name || undefined,
        tool_call: m.toolCall,
        reasoning: m.reasoning,
      }
      if (m.context > 0) modelObj.limit = { context: m.context, input: m.context, output: m.context }
      models[m.id] = modelObj
      if (!defaultModel) defaultModel = m.id
    }
  }

  const provider: TranslatedProvider = {
    name: name.charAt(0).toUpperCase() + name.slice(1),
    options,
    models: Object.keys(models).length > 0 ? models : undefined,
  }
  if (backend.npm) provider.npm = backend.npm
  if (envVars.length > 0) provider.env = envVars

  return { provider, defaultModel }
}
