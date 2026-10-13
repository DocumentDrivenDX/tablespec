import { defineConfig } from '@playwright/test'

/**
 * Link crawl + content validation against a production-like base path.
 *
 * GitHub Pages serves the microsite at /tablespec/. Root-absolute hrefs such as
 * /demos 404 there even when they work on a bare local hugo server.
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: 'link-check.spec.ts',
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,

  use: {
    // Origin only; tests request paths under /tablespec/...
    baseURL: 'http://127.0.0.1:1314',
    headless: true,
    trace: 'retain-on-failure',
  },

  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report-links' }],
  ],

  webServer: {
    command:
      'hugo server --port 1314 --bind 127.0.0.1 ' +
      '--baseURL http://127.0.0.1:1314/tablespec/ ' +
      '--appendPort=false --disableFastRender',
    url: 'http://127.0.0.1:1314/tablespec/',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
