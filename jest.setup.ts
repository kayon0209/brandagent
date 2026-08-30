import '@testing-library/jest-dom'

// useConsumerDraft persists an unsent draft backup keyed per project; a
// leftover backup from one test would flip the next test's load() into
// recovery mode. Tests share one jsdom instance, so clear storage between them.
afterEach(() => {
  try {
    window.sessionStorage.clear()
    window.localStorage.clear()
  } catch {
    /* storage unavailable in this environment */
  }
})
