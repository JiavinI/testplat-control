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

afterEach(() => {
  cleanup()
})
