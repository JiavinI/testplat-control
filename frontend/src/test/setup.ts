import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Ant Design / rc-util 在 jsdom 中依赖 matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  configurable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
})

// 部分 Ant Design 组件依赖 ResizeObserver
class ResizeObserverStub {
  observe() {
    return undefined
  }
  unobserve() {
    return undefined
  }
  disconnect() {
    return undefined
  }
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub)

// jsdom 未实现伪元素 getComputedStyle，antd 会刷警告；提供最小 stub
const originalGetComputedStyle = window.getComputedStyle.bind(window)
window.getComputedStyle = ((elt: Element, pseudoElt?: string | null) => {
  if (pseudoElt) {
    return {
      getPropertyValue: () => '',
    } as unknown as CSSStyleDeclaration
  }
  return originalGetComputedStyle(elt)
}) as typeof window.getComputedStyle

// Node/jsdom 下 localStorage 可能不可用（--localstorage-file 无路径）；提供内存实现
const memoryStore = new Map<string, string>()
const memoryLocalStorage: Storage = {
  get length() {
    return memoryStore.size
  },
  clear() {
    memoryStore.clear()
  },
  getItem(key: string) {
    return memoryStore.has(key) ? memoryStore.get(key)! : null
  },
  key(index: number) {
    return [...memoryStore.keys()][index] ?? null
  },
  removeItem(key: string) {
    memoryStore.delete(key)
  },
  setItem(key: string, value: string) {
    memoryStore.set(key, String(value))
  },
}
Object.defineProperty(window, 'localStorage', {
  configurable: true,
  writable: true,
  value: memoryLocalStorage,
})

afterEach(() => {
  memoryStore.clear()
  cleanup()
})
