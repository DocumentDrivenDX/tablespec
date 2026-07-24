import { defineConfig } from '@playwright/test'

/**
 * Content, navigation, and screenshot suite (local-style base path `/`).
 *
 * Link crawl under production `/tablespec/` base lives in
 * `playwright.link-check.config.ts` (`npm run test:links`).
 */
export default defineConfig({
  testDir: './e2e',
  testIgnore: /link-check\.spec\.ts/,
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,

  use: {
    baseURL: 'http://127.0.0.1:1313',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'on',
  },

  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],

  webServer: {
    command:
      'hugo server --port 1313 --bind 127.0.0.1 ' +
      '--baseURL http://127.0.0.1:1313/ --appendPort=false',
    url: 'http://127.0.0.1:1313/',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
