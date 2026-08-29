import nextJest from 'next/jest.js'

const createJestConfig = nextJest({ dir: './' })

/** @type {import('jest').Config} */
const config = {
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  // next/jest does not translate tsconfig "paths" into moduleNameMapper,
  // so the @ alias is mapped explicitly here.
  moduleNameMapper: {
    '^@/styles/brandflow$': '<rootDir>/src/styles/brandflow.module.css',
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  // node --test owns *.test.mjs and Playwright owns tests/e2e/*.spec.ts;
  // jest only picks up consumer unit/component tests.
  testMatch: ['<rootDir>/tests/unit/**/*.test.ts', '<rootDir>/tests/unit/**/*.test.tsx'],
  passWithNoTests: true,
}

export default createJestConfig(config)
