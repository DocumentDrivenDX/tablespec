// @covers US-038-AC1
// @covers US-038-AC2
// @covers US-038-AC3
// @covers US-038-AC4
// @covers US-038-AC5
import { test, expect } from '@playwright/test'

const article = (page: any) => page.locator('article')

test.describe('Homepage', () => {
  test('loads with hero stating the compile-once promise and source-semantic bronze', async ({ page }) => {
    await page.goto('/')

    await test.step('verify hero headline', async () => {
      await expect(
        page.getByRole('heading', { name: /Definition of done for ingested bronze/i }).first(),
      ).toBeVisible()
    })

    await test.step('verify product description mentions source-semantic bronze', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toContain('source-semantic')
    })

    await test.step('verify primary CTA links to getting-started', async () => {
      await expect(page.getByRole('link', { name: /Start with a UMF/i }).first()).toBeVisible()
    })

    await test.step('verify worked example CTA is visible', async () => {
      await expect(page.getByRole('link', { name: /View the worked example/i }).first()).toBeVisible()
    })

    await test.step('verify blueprint artifact evidence is visible', async () => {
      await expect(page.locator('.ts-artifact-strip').getByText('claims.ingest.sql')).toBeVisible()
      await expect(page.locator('.ts-node-ingested').getByText('typed, validated, keyed')).toBeVisible()
    })

    // Visual baselines drift with theme/CSS and font metrics across runners.
    // Keep a generous ratio so content assertions remain the deploy gate;
    // refresh snapshots with: npm run test:update-snapshots (Linux CI image).
    await test.step('desktop screenshot', async () => {
      await page.setViewportSize({ width: 1280, height: 800 })
      await expect(page).toHaveScreenshot('homepage-desktop.png', {
        fullPage: true,
        maxDiffPixelRatio: 0.12,
      })
    })

    await test.step('mobile screenshot', async () => {
      await page.setViewportSize({ width: 375, height: 812 })
      await expect(page).toHaveScreenshot('homepage-mobile.png', {
        fullPage: true,
        maxDiffPixelRatio: 0.12,
      })
    })
  })
})

test.describe('Worked Example', () => {
  test('loads and walks from UMF to compiled artifacts', async ({ page }) => {
    await page.goto('/worked-example/')

    await expect(page.getByRole('heading', { name: 'Worked Example' }).first()).toBeVisible()
    const body = await page.locator('body').textContent()
    expect(body).toContain('tablespec validate tables/')
    expect(body).toContain('claims.ingest.sql')
    expect(body).toContain('validation-sync')
    expect(body).toContain('source-semantic ingested bronze')
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
      expect(body).toContain('documentdrivendx.github.io/tablespec/simple/')
    })

    await test.step('links to workspace operator guides', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toMatch(/In a workspace/i)
      expect(body).toMatch(/Deploy the app/i)
    })

    await test.step('documents uv and pip install paths', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toContain('uv add tablespec')
      expect(body).toContain('pip install tablespec')
    })

    await test.step('covers UMF loading and compile path', async () => {
      const body = await page.locator('body').textContent()
      expect(body).toContain('UMFLoader')
      expect(body).toContain('generate_sql_ddl')
      expect(body).toContain('tablespec validate')
      expect(body).toContain('--backend dbt')
    })
  })

  test('workspace guide covers demos and opt-in serverless', async ({ page }) => {
    await page.goto('/getting-started/in-a-workspace/')

    await expect(page.getByRole('heading', { name: 'In a workspace' }).first()).toBeVisible()
    const body = await page.locator('body').textContent()
    expect(body).toContain('bootstrap_from_tables')
    expect(body).toContain('northwind-demo')
    expect(body).toContain('kaggle-demo')
    expect(body).toContain('sec-10k-demo')
    expect(body).toContain('databricks_e2e')
  })

  test('deploy-the-app guide covers provision and metadata home', async ({ page }) => {
    await page.goto('/getting-started/deploy-the-app/')

    await expect(page.getByRole('heading', { name: 'Deploy the app' }).first()).toBeVisible()
    const body = await page.locator('body').textContent()
    expect(body).toContain('provision.py')
    expect(body).toContain('PROFILER_METADATA_CATALOG')
    expect(body).toContain('DATABRICKS_WAREHOUSE_ID')
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
    expect(body).toContain('generate')
    expect(body).toContain('validate')
    expect(body).toContain('emit')
    expect(body).toContain('validation-sync')
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
    expect(body).toContain('Northwind')
    expect(body).toContain('Kaggle')
    expect(body).toContain('SEC 10-K')
    expect(body).toContain('tablespec-demo')
  })
})

test.describe('Navigation', () => {
  test('top nav reaches all required sections', async ({ page }) => {
    await page.goto('/')
    const nav = page.getByRole('navigation').first()

    for (const [name, urlPattern] of [
      ['Getting Started', /\/getting-started/],
      ['Worked Example', /\/worked-example/],
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
    await page.getByRole('link', { name: /Start with a UMF/i }).first().click()
    await expect(page).toHaveURL(/\/getting-started/)
  })

  test('top nav marks current page semantically', async ({ page }) => {
    await page.goto('/worked-example/')
    await expect(page.getByRole('navigation').first().getByRole('link', {
      name: 'Worked Example',
      current: 'page',
    })).toBeVisible()
  })

  test('mobile: no horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    for (const path of ['/', '/getting-started/', '/worked-example/', '/concepts/', '/cli-reference/']) {
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
      '/getting-started/first-15-minutes/',
      '/getting-started/in-a-workspace/',
      '/getting-started/deploy-the-app/',
      '/worked-example/',
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
