/** 与后端 EnvironmentResponse / AccountResponse / LoginProfilesResponse 对齐。列表不含凭据。 */

export interface ProjectEnvironment {
  env: string
  enabled: boolean
  api_hosts: Record<string, string>
  timeout_seconds: number | null
  case_params: Record<string, unknown>
  revision: number
  updated_by: string | null
}

export interface EnvironmentBody {
  env: string
  api_hosts: Record<string, string>
  timeout_seconds: number | null
  case_params: Record<string, unknown>
  enabled: boolean
}

/** 除 revision 外都可省略；省略的字段不会被后端改写。 */
export interface EnvironmentUpdate {
  revision: number
  api_hosts?: Record<string, string>
  timeout_seconds?: number | null
  case_params?: Record<string, unknown>
  enabled?: boolean
}

export interface TestAccount {
  account_name: string
  display_name: string | null
  business_role: string | null
  login_profile: string
  enabled: boolean
  revision: number
  updated_by: string | null
}

export interface AccountBody {
  account_name: string
  display_name?: string | null
  business_role?: string | null
  login_profile: string
  credentials: Record<string, string>
  enabled: boolean
}

export interface AccountUpdate {
  revision: number
  display_name?: string | null
  business_role?: string | null
  login_profile?: string
  enabled?: boolean
  /** 省略表示不改凭据。有值时整表替换。 */
  credentials?: Record<string, string>
}

export interface LoginProfile {
  name: string
  credential_fields: string[]
  unavailable_reason?: string | null
}

export interface LoginProfiles {
  commit_sha: string
  profiles: LoginProfile[]
}

export interface AccountCredentials {
  account_name: string
  credentials: Record<string, string>
}
