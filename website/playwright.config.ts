import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 60000,

  use: {
    baseURL: 'http://127.0.0.1:1313',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'on',
  },

  reporter: [
    ['list'],
    ['html', { open: 'never' }],
  ],

  webServer: {
    command: 'hugo server --port 1313 --baseURL http://127.0.0.1:1313/ --appendPort=false',
    port: 1313,
    reuseExistingServer: !process.env.CI,
    timeout: 60000,
  },
})
