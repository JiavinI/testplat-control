/**
 * 读取 Agent 2 冻结的契约示例（仓库根 docs/phase3_3/examples/，Control 12a8d6a）。
 * 用 node:fs 而不是 `?raw` import：后者会被 Vite 的 fs.allow 拒绝，而放宽 fs.allow
 * 会连带扩大 dev server 的可读范围，不值得。仅供测试使用。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

const EXAMPLES_DIR = path.resolve(process.cwd(), '..', 'docs', 'phase3_3', 'examples')

export function loadContractExample(name: string): unknown {
  return JSON.parse(readFileSync(path.join(EXAMPLES_DIR, name), 'utf8'))
}
