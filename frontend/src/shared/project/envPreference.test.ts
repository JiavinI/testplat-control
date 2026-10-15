import { afterEach, describe, expect, it } from 'vitest'
import {
  readPreferredEnv,
  resolveInitialEnv,
  writePreferredEnv,
} from './envPreference'

afterEach(() => {
  window.localStorage.clear()
})

describe('envPreference', () => {
  it('记住并读回上次选择', () => {
    writePreferredEnv('main/gsb', 'staging')
    expect(readPreferredEnv('main/gsb')).toBe('staging')
  })

  it('resolveInitialEnv 优先 localStorage，否则 default_env', () => {
    expect(resolveInitialEnv('main/gsb', ['test', 'staging'], 'test')).toBe('test')
    writePreferredEnv('main/gsb', 'staging')
    expect(resolveInitialEnv('main/gsb', ['test', 'staging'], 'test')).toBe(
      'staging',
    )
    writePreferredEnv('main/gsb', 'gone')
    expect(resolveInitialEnv('main/gsb', ['test', 'staging'], 'test')).toBe('test')
  })
})
