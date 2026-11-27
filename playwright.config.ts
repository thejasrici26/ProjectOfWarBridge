import { randomBytes, randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { defineConfig } from '@playwright/test'

const adminEmail = process.env.WARBRIDGE_E2E_ADMIN_EMAIL ?? 'e2e-admin@example.test'
const adminPassword = process.env.WARBRIDGE_E2E_ADMIN_PASSWORD ?? 'e2e-admin-password-local-only'
const userPassword = process.env.WARBRIDGE_E2E_USER_PASSWORD ?? 'e2e-user-password-local-only'
const databasePath = path.join(tmpdir(), `warbridge-e2e-${randomUUID()}.db`)
const localPython = path.join(process.cwd(), '.venv', 'Scripts', 'python.exe')
const python = process.env.PYTHON
  ?? (process.platform === 'win32' && existsSync(localPython) ? localPython : 'python')
const frontendPort = process.env.CI
  ? '4173'
  : process.env.WARBRIDGE_E2E_FRONTEND_PORT ?? process.env.PORT ?? '8443'

process.env.WARBRIDGE_E2E_ADMIN_EMAIL = adminEmail
process.env.WARBRIDGE_E2E_ADMIN_PASSWORD = adminPassword
process.env.WARBRIDGE_E2E_USER_PASSWORD = userPassword

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport: { width: 1440, height: 1000 },
  },
  webServer: [
    {
      command: `${process.platform === 'win32' ? `"${python}"` : python} app.py`,
      url: 'http://127.0.0.1:5000/api/health/live',
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        WARBRIDGE_ENV: 'development',
        WARBRIDGE_DB: databasePath,
        WARBRIDGE_ADMIN_EMAIL: adminEmail,
        WARBRIDGE_ADMIN_PASSWORD: adminPassword,
        SECRET_KEY: randomBytes(32).toString('hex'),
      },
    },
    {
      command: `${process.platform === 'win32' ? 'corepack pnpm' : 'pnpm'} dev -- --host 127.0.0.1 --port ${frontendPort}`,
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { PORT: frontendPort },
    },
  ],
})
