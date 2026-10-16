/** 与后端 MeResponse / AuthBody 对齐。响应只有用户名，没有密码哈希。 */
export interface MeResponse {
  username: string
}

export interface AuthBody {
  username: string
  password: string
}
