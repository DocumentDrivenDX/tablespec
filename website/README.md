# tablespec product microsite

Hugo + Hextra site published at `https://documentdrivendx.github.io/tablespec/`.

## Site-relative links (baseURL)

`hugo.yaml` sets `baseURL` with a path prefix (`/tablespec/`). **Always use
root-absolute site paths** in content and shortcodes:

```markdown
[Demos](/demos/)
{{< card link="/demos/" title="Demos" >}}
```

Do **not** use `../demos/` workarounds. Markdown render hooks already apply
baseURL correctly. Hextra card/hero shortcodes are overridden under
`layouts/` to use `layouts/_partials/utils/site-href.html`, which trims a
leading `/` before `relURL` so `/demos/` becomes `/tablespec/demos/`.

Any new shortcode that emits `href` for an internal path must call:

```go-html-template
{{ partial "utils/site-href.html" $link }}
```

## Tests

```bash
# from repo root
make website-install
make website-test          # content suite + /tablespec/ link crawl

# from website/
npm run test:content
npm run test:links
npm run test:all
```

CI: `.github/workflows/microsite.yml` and the pre-deploy gate in
`publish-microsite.yml`.
