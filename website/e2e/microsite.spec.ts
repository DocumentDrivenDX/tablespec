import { test, expect } from '@playwright/test'

const article = (page: any) => page.locator('article')

test.describe('Homepage', () => {
  test('loads with hero stating the compile-once promise and source-semantic bronze', async ({ page }) => {
    await page.goto('/')

    await test.step('verify hero headline', async () => {
      await expect(
        page.getByRole('heading', { name: /Define the table once/i }).first(),
      ).toBeVisible()
    })

    await test.step('verify product description mentions source-semantic bronze', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toContain('source-semantic')
    })

    await test.step('verify primary CTA links to getting-started', async () => {
      await expect(page.getByRole('link', { name: /Get Started/i }).first()).toBeVisible()
    })

    await test.step('verify concepts CTA links to concepts', async () => {
      await expect(page.getByRole('link', { name: /Core Concepts/i }).first()).toBeVisible()
    })

    await test.step('desktop screenshot', async () => {
      await page.setViewportSize({ width: 1280, height: 800 })
      await expect(page).toHaveScreenshot('homepage-desktop.png', {
        fullPage: true,
        maxDiffPixelRatio: 0.05,
      })
    })

    await test.step('mobile screenshot', async () => {
      await page.setViewportSize({ width: 375, height: 812 })
      await expect(page).toHaveScreenshot('homepage-mobile.png', {
        fullPage: true,
        maxDiffPixelRatio: 0.05,
      })
    })
  })
})

test.describe('Getting Started', () => {
  test('loads and documents install from package index', async ({ page }) => {
    await page.goto('/getting-started/')

    await test.step('verify page loads', async () => {
      await expect(page.getByRole('heading', { name: 'Getting Started' }).first()).toBeVisible()
    })

    await test.step('install command uses project package index', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toContain('easel.github.io/tablespec/simple/')
    })

    await test.step('documents uv and pip install paths', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toContain('uv add tablespec')
      expect(body).toContain('pip install tablespec')
    })

    await test.step('covers UMF loading and compile path', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toContain('load_umf_from_yaml')
      expect(body).toContain('generate_sql_ddl')
    })
  })
})

test.describe('Core Concepts', () => {
  test('index lists concept subpages', async ({ page }) => {
    await page.goto('/concepts/')

    await expect(article(page).getByRole('link', { name: /Raw, ingested, and silver/i })).toBeVisible()
    await expect(article(page).getByRole('link', { name: /Universal Metadata Format/i })).toBeVisible()
    await expect(article(page).getByRole('link', { name: /Compiled artifacts/i })).toBeVisible()
    await expect(article(page).getByRole('link', { name: /Validation model/i })).toBeVisible()
  })

  test('raw-ingested-silver page states the layer boundary correctly', async ({ page }) => {
    await page.goto('/concepts/raw-ingested-silver/')

    await test.step('page heading is present', async () => {
      await expect(page.getByRole('heading', { name: /Raw, ingested, and silver/i }).first()).toBeVisible()
    })

    await test.step('ingested bronze section is present', async () => {
      await expect(page.getByRole('heading', { name: /Ingested bronze/i })).toBeVisible()
    })

    await test.step('silver section is present', async () => {
      await expect(article(page).locator('h3').filter({ hasText: 'Silver' }).first()).toBeVisible()
    })

    await test.step('states that ingested preserves source semantics', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toContain('Preserves source semantics')
    })

    await test.step('states that silver covers conformance survivorship entity resolution enrichment and dimensional modeling', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toMatch(/survivorship/i)
      expect(body).toMatch(/entity resolution/i)
      expect(body).toMatch(/enrichment/i)
      expect(body).toMatch(/dimensional modeling/i)
    })
  })
})

test.describe('CLI Reference', () => {
  test('loads and covers key commands', async ({ page }) => {
    await page.goto('/cli-reference/')

    await expect(page.getByRole('heading', { name: 'CLI Reference' }).first()).toBeVisible()

    const body = await page.locator('body').textContent()
    expect(body).toContain('compile')
    expect(body).toContain('validate')
    expect(body).toContain('gx baseline')
  })
})

test.describe('API Reference', () => {
  test('entry point loads and names core symbols', async ({ page }) => {
    await page.goto('/api-reference/')

    await expect(page.getByRole('heading', { name: 'API Reference' }).first()).toBeVisible()

    const body = await page.locator('body').textContent()
    expect(body).toContain('load_umf_from_yaml')
    expect(body).toContain('generate_sql_ddl')
    expect(body).toContain('UMF')
  })
})

test.describe('Demos', () => {
  test('entry point loads and links to demo assets', async ({ page }) => {
    await page.goto('/demos/')

    await expect(page.getByRole('heading', { name: 'Demos' }).first()).toBeVisible()

    const body = await page.locator('body').textContent()
    expect(body).toContain('tablespec-demo')
  })
})

test.describe('Navigation', () => {
  test('top nav reaches all required sections', async ({ page }) => {
    await page.goto('/')
    const nav = page.getByRole('navigation').first()

    for (const [name, urlPattern] of [
      ['Getting Started', /\/getting-started/],
      ['Concepts', /\/concepts/],
      ['CLI Reference', /\/cli-reference/],
      ['API Reference', /\/api-reference/],
      ['Demos', /\/demos/],
    ] as const) {
      await page.goto('/')
      await nav.getByRole('link', { name }).first().click()
      await expect(page).toHaveURL(urlPattern)
    }
  })

  test('homepage CTA navigates to getting-started', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /Get Started/i }).first().click()
    await expect(page).toHaveURL(/\/getting-started/)
  })

  test('mobile: no horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    for (const path of ['/', '/getting-started/', '/concepts/', '/cli-reference/']) {
      await page.goto(path)
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      )
      expect(overflow, `${path} should not scroll horizontally on mobile`).toBeLessThanOrEqual(1)
    }
  })
})

test.describe('Build inventory', () => {
  test('all required top-level pages resolve', async ({ page }) => {
    const required = [
      '/',
      '/getting-started/',
      '/concepts/',
      '/concepts/raw-ingested-silver/',
      '/cli-reference/',
      '/api-reference/',
      '/demos/',
    ]
    for (const path of required) {
      const response = await page.request.get(path)
      expect(response.status(), `${path} should return 200`).toBe(200)
    }
  })
})
