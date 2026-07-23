/**
 * Production-baseURL link crawl + content validation for the microsite.
 *
 * Serves under `/tablespec/` (same path prefix as GitHub Pages) so root-absolute
 * hrefs like `/demos` fail here the same way they fail in production.
 *
 * Run: `npm run test:links` (from website/)
 * CI: `.github/workflows/microsite.yml` and publish-microsite pre-deploy gate.
 */
// @covers US-038-AC1
// @covers US-038-AC2
// @covers US-038-AC5
import { test, expect, type APIRequestContext } from '@playwright/test'

/** Path prefix matching GitHub Pages project site (see website/hugo.yaml baseURL). */
const SITE_PREFIX = '/tablespec'

const SEED_PATHS = [
  `${SITE_PREFIX}/`,
  `${SITE_PREFIX}/getting-started/`,
  `${SITE_PREFIX}/getting-started/in-a-workspace/`,
  `${SITE_PREFIX}/getting-started/deploy-the-app/`,
  `${SITE_PREFIX}/worked-example/`,
  `${SITE_PREFIX}/concepts/`,
  `${SITE_PREFIX}/concepts/raw-ingested-silver/`,
  `${SITE_PREFIX}/concepts/umf/`,
  `${SITE_PREFIX}/concepts/artifacts/`,
  `${SITE_PREFIX}/concepts/validation/`,
  `${SITE_PREFIX}/cli-reference/`,
  `${SITE_PREFIX}/api-reference/`,
  `${SITE_PREFIX}/demos/`,
] as const

/** Required content per path (path relative to origin, including SITE_PREFIX). */
const CONTENT_CHECKS: ReadonlyArray<{ path: string; mustInclude: string[] }> = [
  {
    path: `${SITE_PREFIX}/`,
    mustInclude: ['source-semantic', 'Start with a UMF', 'ingested bronze'],
  },
  {
    path: `${SITE_PREFIX}/getting-started/`,
    mustInclude: [
      'documentdrivendx.github.io/tablespec/simple/',
      'In a workspace',
      'Deploy the app',
      'tablespec validate',
    ],
  },
  {
    path: `${SITE_PREFIX}/getting-started/in-a-workspace/`,
    mustInclude: [
      'bootstrap_from_tables',
      'northwind-demo',
      'kaggle-demo',
      'sec-10k-demo',
      'databricks_e2e',
    ],
  },
  {
    path: `${SITE_PREFIX}/getting-started/deploy-the-app/`,
    mustInclude: [
      'provision.py',
      'PROFILER_METADATA_CATALOG',
      'DATABRICKS_WAREHOUSE_ID',
    ],
  },
  {
    path: `${SITE_PREFIX}/demos/`,
    mustInclude: ['Northwind', 'Kaggle', 'SEC 10-K', 'tablespec-demo'],
  },
  {
    path: `${SITE_PREFIX}/worked-example/`,
    mustInclude: [
      'tablespec validate tables/',
      'claims.ingest.sql',
      'source-semantic ingested bronze',
    ],
  },
  {
    path: `${SITE_PREFIX}/concepts/raw-ingested-silver/`,
    mustInclude: [
      'Preserves source semantics',
      'Survivorship',
      'Entity resolution',
    ],
  },
  {
    path: `${SITE_PREFIX}/cli-reference/`,
    mustInclude: ['generate', 'validate', 'emit', 'validation-sync'],
  },
  {
    path: `${SITE_PREFIX}/api-reference/`,
    mustInclude: ['load_umf_from_yaml', 'generate_sql_ddl', 'UMF'],
  },
]

type BrokenLink = {
  from: string
  href: string
  resolved: string
  status: number
  reason: string
}

function isAssetPath(pathname: string): boolean {
  return /\.(css|js|map|png|jpe?g|gif|svg|ico|webp|woff2?|ttf|json)$/i.test(
    pathname,
  )
}

/**
 * Normalize a site path. HTML section pages are forced to a trailing slash so
 * relative hrefs like ``../demos/`` resolve the same way browsers do for
 * ``/tablespec/getting-started/`` (not the file-like ``.../getting-started``).
 */
function normalizePath(pathname: string): string {
  if (!pathname || pathname === '/') {
    return `${SITE_PREFIX}/`
  }
  let path = pathname.replace(/\/{2,}/g, '/')
  if (!path.startsWith('/')) {
    path = `/${path}`
  }
  path = path.replace(/\/index\.html$/i, '/')
  if (!isAssetPath(path) && !path.endsWith('/')) {
    path = `${path}/`
  }
  return path
}

/** Directory form of the current page for relative URL resolution. */
function directoryBase(fromPath: string): string {
  if (fromPath.endsWith('/')) {
    return fromPath
  }
  if (isAssetPath(fromPath)) {
    const idx = fromPath.lastIndexOf('/')
    return idx >= 0 ? fromPath.slice(0, idx + 1) : '/'
  }
  return `${fromPath}/`
}

function resolveInternalHref(
  href: string,
  fromPath: string,
  origin: string,
): { kind: 'internal'; path: string } | { kind: 'skip'; reason: string } | {
  kind: 'external'
  url: string
} {
  const trimmed = href.trim()
  if (
    !trimmed ||
    trimmed.startsWith('#') ||
    trimmed.startsWith('mailto:') ||
    trimmed.startsWith('tel:') ||
    trimmed.startsWith('javascript:') ||
    trimmed.startsWith('data:')
  ) {
    return { kind: 'skip', reason: 'non-navigational' }
  }

  let url: URL
  try {
    url = new URL(trimmed, `${origin}${directoryBase(fromPath)}`)
  } catch {
    return { kind: 'skip', reason: 'unparseable' }
  }

  if (url.origin !== origin) {
    return { kind: 'external', url: url.href }
  }

  // Same-origin but outside the site prefix is the production 404 class
  // (e.g. href=/demos when the site lives at /tablespec/demos/).
  const path = normalizePath(url.pathname)
  return { kind: 'internal', path }
}

function extractHrefs(html: string): string[] {
  const hrefs: string[] = []
  const re = /\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/gi
  let match: RegExpExecArray | null
  while ((match = re.exec(html)) !== null) {
    const value = match[1] ?? match[2] ?? match[3] ?? ''
    if (value) {
      hrefs.push(value)
    }
  }
  return hrefs
}

async function fetchStatus(
  request: APIRequestContext,
  origin: string,
  path: string,
): Promise<{ status: number; contentType: string; body?: string }> {
  const response = await request.get(`${origin}${path}`, {
    maxRedirects: 5,
    failOnStatusCode: false,
  })
  const contentType = response.headers()['content-type'] ?? ''
  const status = response.status()
  if (status >= 400 || !contentType.includes('text/html')) {
    return { status, contentType }
  }
  return { status, contentType, body: await response.text() }
}

test.describe('Microsite link crawl (production base path)', () => {
  test('all internal links resolve under /tablespec/', async ({
    request,
    baseURL,
  }) => {
    expect(baseURL, 'playwright baseURL must be set').toBeTruthy()
    const origin = new URL(baseURL!).origin

    const queue: string[] = [...SEED_PATHS]
    const visited = new Set<string>()
    const via = new Map<string, { from: string; href: string }>()
    for (const seed of SEED_PATHS) {
      via.set(seed, { from: '(seed)', href: seed })
    }

    const broken: BrokenLink[] = []
    const outsidePrefix: BrokenLink[] = []

    while (queue.length > 0) {
      const path = queue.pop()!
      if (visited.has(path)) {
        continue
      }
      visited.add(path)

      const source = via.get(path) ?? { from: '(unknown)', href: path }
      const result = await fetchStatus(request, origin, path)
      if (result.status >= 400) {
        broken.push({
          from: source.from,
          href: source.href,
          resolved: path,
          status: result.status,
          reason: 'page fetch failed',
        })
        continue
      }
      if (!result.body) {
        continue
      }

      for (const href of extractHrefs(result.body)) {
        const resolved = resolveInternalHref(href, path, origin)
        if (resolved.kind === 'skip' || resolved.kind === 'external') {
          continue
        }

        const target = resolved.path
        if (!target.startsWith(`${SITE_PREFIX}/`) && target !== SITE_PREFIX) {
          outsidePrefix.push({
            from: path,
            href,
            resolved: target,
            status: 0,
            reason: `same-origin link outside ${SITE_PREFIX}/ (will 404 on GitHub Pages)`,
          })
          continue
        }

        // Static assets: status-check only, do not crawl as HTML.
        if (isAssetPath(target)) {
          if (!visited.has(target)) {
            visited.add(target)
            const asset = await fetchStatus(request, origin, target)
            if (asset.status >= 400) {
              broken.push({
                from: path,
                href,
                resolved: target,
                status: asset.status,
                reason: 'asset fetch failed',
              })
            }
          }
          continue
        }

        if (!visited.has(target) && !queue.includes(target)) {
          via.set(target, { from: path, href })
          queue.push(target)
        }
      }
    }

    const problems = [...broken, ...outsidePrefix]
    expect(
      problems,
      problems
        .map(
          (p) =>
            `${p.from} -> ${p.href} => ${p.resolved} (${p.status || 'n/a'}: ${p.reason})`,
        )
        .join('\n') || 'no problems',
    ).toEqual([])

    // Sanity: crawl should have seen at least every seed page.
    for (const seed of SEED_PATHS) {
      expect(visited.has(seed), `seed visited: ${seed}`).toBe(true)
    }
  })
})

test.describe('Microsite content validation (production base path)', () => {
  for (const check of CONTENT_CHECKS) {
    test(`${check.path} includes required content`, async ({ request, baseURL }) => {
      const origin = new URL(baseURL!).origin
      const result = await fetchStatus(request, origin, check.path)
      expect(result.status, `${check.path} status`).toBe(200)
      expect(result.body, `${check.path} body`).toBeTruthy()
      const body = result.body!
      for (const fragment of check.mustInclude) {
        expect(body, `${check.path} should include ${JSON.stringify(fragment)}`).toContain(
          fragment,
        )
      }
    })
  }
})
