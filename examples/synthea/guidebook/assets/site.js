/* Guidebook: catalog + lineage site. Renders home, group, and table pages from the
 * page's inline JSON (#page-data) plus the shared window.CATALOG index.
 * Table pages keep their state in the URL hash: #col=<name>&tab=<tab>. */
(function () {
  "use strict";

  const PAGE = JSON.parse(document.getElementById("page-data").textContent);
  const CATALOG = window.CATALOG || { groups: [] };
  const ROOT = PAGE.root || "";
  const STANDALONE = !!PAGE.standalone;
  const DOC = PAGE.doc;
  const UNSET = 999;

  // ------------------------------------------------------------------ utils

  function el(tag, attrs, ...children) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : String(v));
    }
    for (const c of children) {
      if (c === null || c === undefined || c === false) continue;
      n.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return n;
  }
  // Server-side escaped HTML (format_prose output) only.
  function trusted(htmlText) {
    const d = el("div", { class: "prose" });
    d.innerHTML = htmlText;
    return d;
  }
  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }
  // Table ids are "group.table", or just "table" for UMFs at the discovery root.
  function splitId(id) { const i = id.lastIndexOf("."); return [id.slice(0, Math.max(i, 0)), id.slice(i + 1)]; }
  function groupPrefix(g) { return g ? g + "/" : ""; }
  function colOf(cid) { const i = cid.lastIndexOf("."); return [cid.slice(0, i), cid.slice(i + 1)]; }
  function typeClass(t) { return t ? (t === "generated" ? "generated" : "provided") : "missing"; }
  function typeChip(t) { return el("span", { class: "chip t-" + typeClass(t) }, t || "not found"); }
  function leafLabel(c) {
    if (!c || !c.leaf_kind) return "";
    if (c.leaf_kind === "filename_capture") return "filename group " + (c.capture_group ?? "?");
    if (c.leaf_kind === "constant") return "constant " + (c.constant ?? "");
    return c.leaf_kind.replace(/_/g, " ");
  }
  function formatOf(f) {
    if (!f) return "";
    return ["delimiter " + (f.delimiter == null ? "auto" : JSON.stringify(f.delimiter)),
      f.encoding || "utf-8", f.header === false ? "no header" : "header"].join(", ");
  }
  function hashFor(col, tab, view) {
    const p = new URLSearchParams();
    if (col) p.set("col", col);
    if (tab) p.set("tab", tab);
    if (view) p.set("view", view);
    return p.toString();
  }
  function currentTableId() { return PAGE.kind === "table" ? DOC.id : null; }
  function knownTable(tid) {
    const [g, t] = splitId(tid);
    const group = CATALOG.groups.find((x) => x.name === g);
    return !!(group && group.tables.some((x) => x.name === t));
  }
  // href to a table page (optionally a column/tab), or null when it can't be linked.
  function tableHref(tid, col, tab) {
    const hash = hashFor(col, tab);
    if (tid === currentTableId()) return "#" + hash;
    if (STANDALONE || !knownTable(tid)) return null;
    const [g, t] = splitId(tid);
    return ROOT + groupPrefix(g) + t + ".html" + (hash ? "#" + hash : "");
  }
  function tableLink(tid, label, col, tab) {
    const href = tableHref(tid, col, tab);
    const text = label ?? tid;
    return href ? el("a", { href }, text) : el("span", {}, text);
  }
  function columnLink(cid, tab) {
    const [tid, name] = colOf(cid);
    return tableLink(tid, cid, name, tab);
  }
  function kv(pairs) {
    const dl = el("dl", { class: "kv" });
    for (const [k, v] of pairs) {
      if (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length)) continue;
      dl.append(el("dt", {}, k), el("dd", {}, v));
    }
    return dl;
  }
  function linkList(ids) {
    const d = el("div", { class: "linklist" });
    for (const id of ids) d.append(tableLink(id));
    return d;
  }
  function sortableTable(headers, rows, onRow) {
    // headers: [{label, key}] ; rows: [{cells: [node|string], keys: {key: value}, data}]
    const tbody = el("tbody");
    let sortKey = null, asc = true;
    function draw() {
      const list = rows.slice();
      if (sortKey) {
        list.sort((a, b) => {
          const x = a.keys[sortKey], y = b.keys[sortKey];
          const r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
          return asc ? r : -r;
        });
      }
      tbody.replaceChildren();
      for (const r of list) {
        const tr = el("tr", onRow ? { class: "clickable", onclick: () => onRow(r) } : {});
        for (const c of r.cells) tr.append(el("td", {}, c));
        tbody.append(tr);
      }
    }
    const head = el("tr");
    for (const h of headers) {
      head.append(el("th", {
        class: h.key ? "sortable" : null,
        onclick: h.key ? () => { asc = sortKey === h.key ? !asc : true; sortKey = h.key; draw(); } : null,
      }, h.label));
    }
    draw();
    return el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, head), tbody));
  }
  function empty(text) { return el("div", { class: "empty" }, text); }

  // ---------------------------------------------------------------- shell

  function searchBox() {
    let entries = null;
    function index() {
      if (entries) return entries;
      entries = [];
      for (const g of CATALOG.groups) {
        for (const t of g.tables) {
          const base = ROOT + groupPrefix(g.name) + t.name + ".html";
          const where = g.name ? g.name + "." + t.name : t.name;
          entries.push({ kind: 0, name: t.name, sub: (g.name ? g.name + " · " : "") + (t.type || "table"), desc: t.desc,
            href: base, hay: (t.name + " " + g.name + " " + t.desc).toLowerCase() });
          for (const c of t.cols) {
            entries.push({ kind: 1, name: c[0], sub: where + " · " + c[1], desc: c[2],
              href: base + "#col=" + encodeURIComponent(c[0]),
              hay: (c[0] + " " + t.name + " " + g.name + " " + c[2]).toLowerCase() });
          }
        }
      }
      return entries;
    }
    const input = el("input", { type: "search", placeholder: "Search tables & columns", "aria-label": "Search" });
    const results = el("ul", { class: "results", hidden: true });
    let hits = [], active = 0;
    function run() {
      const q = input.value.trim().toLowerCase();
      results.replaceChildren();
      if (!q) { results.hidden = true; return; }
      const tokens = q.split(/\s+/);
      hits = index().filter((e) => tokens.every((tok) => e.hay.includes(tok)));
      const joined = tokens.join("_");
      const rank = (e) => {
        const n = e.name.toLowerCase();
        const r = n === joined ? 0 : n.startsWith(joined) ? 1 : n.includes(joined) ? 2
          : tokens.every((tok) => n.includes(tok)) ? 3 : 4;
        return r + e.kind * 0.5;
      };
      hits.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
      hits = hits.slice(0, 40);
      active = 0;
      if (!hits.length) results.append(el("li", { class: "empty" }, "No matches"));
      hits.forEach((h, i) => {
        results.append(el("li", { class: i === 0 ? "active" : null, onmousedown: () => open(h) },
          el("div", { class: "rname" }, h.name, " ", el("span", { class: "badge" }, h.kind ? "column" : "table")),
          el("div", { class: "rsub" }, h.sub + (h.desc ? " — " + h.desc : ""))));
      });
      results.hidden = false;
    }
    function open(h) {
      input.value = "";
      results.hidden = true;
      input.blur();
      location.href = h.href;
    }
    function move(d) {
      if (!hits.length) return;
      active = (active + d + hits.length) % hits.length;
      [...results.children].forEach((li, i) => li.classList.toggle("active", i === active));
      results.children[active].scrollIntoView({ block: "nearest" });
    }
    input.addEventListener("input", run);
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown") { ev.preventDefault(); move(1); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); move(-1); }
      else if (ev.key === "Enter" && hits[active]) { open(hits[active]); }
      else if (ev.key === "Escape") { input.value = ""; run(); input.blur(); }
    });
    input.addEventListener("blur", () => setTimeout(() => { results.hidden = true; }, 150));
    input.addEventListener("focus", () => { if (input.value) run(); });
    document.addEventListener("keydown", (ev) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
      if ((ev.key === "/" && !typing) || (ev.key === "k" && (ev.metaKey || ev.ctrlKey))) {
        ev.preventDefault();
        input.focus();
        input.select();
      }
    });
    return el("div", { class: "search" }, input, el("kbd", {}, "/"), results);
  }

  function shell(crumbs) {
    const title = PAGE.title || "Catalog";
    const top = el("header", { class: "topbar" },
      STANDALONE ? el("span", { class: "brand" }, title) : el("a", { class: "brand", href: ROOT + "index.html" }, title),
      el("nav", { class: "crumbs" }, ...crumbs),
      el("span", { class: "spacer" }),
      STANDALONE ? null : searchBox());
    const sidebar = el("aside", { class: "sidebar" });
    const main = el("main", { class: "main" });
    const app = document.getElementById("app");
    app.replaceChildren(top, el("div", { class: "layout" }, sidebar, main));
    if (PAGE.provenance_sha) {
      document.body.append(el("footer", { class: "footer" }, "Generated from ", el("code", {}, PAGE.provenance_sha)));
    }
    return { sidebar, main };
  }
  function sep() { return el("span", { class: "sep" }, "▸"); }

  function upLink(href, label) {
    return el("a", { class: "uplink", href }, "↑ " + label);
  }

  function filterInput(list, placeholder) {
    return el("input", {
      type: "search", placeholder, "aria-label": placeholder,
      oninput: (ev) => {
        const q = ev.target.value.toLowerCase();
        for (const li of list.querySelectorAll("li[data-name]")) {
          li.hidden = !li.dataset.name.toLowerCase().includes(q);
        }
      },
    });
  }

  // ----------------------------------------------------------------- DAG

  // cardsByLayer: [[{el, anchors: {id: element}}]] left to right; links: [{from, to, title, onclick}]
  function drawDag(container, cardsByLayer, links) {
    container.replaceChildren();
    const wrap = el("div", { class: "layers" });
    const anchors = {};
    for (const layer of cardsByLayer) {
      const lEl = el("div", { class: "layer" });
      for (const card of layer) { lEl.append(card.el); Object.assign(anchors, card.anchors); }
      wrap.append(lEl);
    }
    container.append(wrap);
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("width", wrap.scrollWidth);
    svg.setAttribute("height", wrap.scrollHeight);
    const origin = wrap.getBoundingClientRect();
    for (const l of links) {
      const a = anchors[l.from], b = anchors[l.to];
      if (!a || !b) continue;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const x1 = ra.right - origin.left, y1 = ra.top + ra.height / 2 - origin.top;
      const x2 = rb.left - origin.left, y2 = rb.top + rb.height / 2 - origin.top;
      const mx = (x1 + x2) / 2;
      const p = document.createElementNS(svgNS, "path");
      p.setAttribute("d", `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`);
      const t = document.createElementNS(svgNS, "title");
      t.textContent = l.title || "";
      p.append(t);
      if (l.onclick) {
        p.addEventListener("click", () => {
          svg.querySelectorAll("path.sel").forEach((q) => q.classList.remove("sel"));
          p.classList.add("sel");
          l.onclick();
        });
      }
      svg.append(p);
    }
    container.prepend(svg);
  }

  // Longest distance from `start` walking `upstream` (id -> [ids]); leaves pinned to the max depth.
  function layerize(start, upstream) {
    const depth = {};
    const stack = [[start, 0]];
    while (stack.length) {
      const [id, d] = stack.pop();
      if ((depth[id] ?? -1) >= d || d > 200) continue;
      depth[id] = d;
      for (const u of upstream(id)) stack.push([u, d + 1]);
    }
    const ids = Object.keys(depth);
    const max = Math.max(0, ...ids.map((id) => depth[id]));
    for (const id of ids) if (!upstream(id).length) depth[id] = max;
    return { ids, depth, max };
  }

  // ---------------------------------------------------------------- home

  function renderHome() {
    const { sidebar, main } = shell([]);
    const groups = DOC.groups || [];
    const list = el("ul", { class: "navlist" }, el("li", { class: "group" }, "Groups"));
    for (const g of groups) {
      list.append(el("li", { "data-name": g.name },
        STANDALONE ? el("span", {}, g.name) : el("a", { href: ROOT + g.name + "/index.html" }, g.name),
        el("span", { class: "badge" }, plural(g.tables.length, "table"))));
    }
    sidebar.append(list);
    const total = groups.reduce((n, g) => n + g.tables.length, 0);
    main.append(el("div", { class: "pagehead" },
      el("h1", {}, PAGE.title),
      el("div", { class: "sub" }, plural(groups.length, "group") + " · " + plural(total, "table"))));
    main.append(empty("Select a group on the left."));
  }

  // ---------------------------------------------------------------- group

  // A group's table list; also the home page of a flat (ungrouped) corpus.
  function renderGroup() {
    const flat = !DOC.name;
    const { sidebar, main } = shell(flat ? [] : [sep(), el("span", {}, DOC.name)]);
    const list = el("ul", { class: "navlist" });
    const kinds = [["Source tables", (t) => t.table_type !== "generated"], ["Generated", (t) => t.table_type === "generated"]];
    const tid = (t) => (DOC.name ? DOC.name + "." : "") + t.name;
    for (const [label, pred] of kinds) {
      const tables = DOC.tables.filter(pred);
      if (!tables.length) continue;
      list.append(el("li", { class: "group" }, label + " (" + tables.length + ")"));
      for (const t of tables) {
        list.append(el("li", { "data-name": t.name },
          tableLink(tid(t), t.name), el("span", { class: "badge" }, t.column_count)));
      }
    }
    sidebar.append(flat || STANDALONE ? "" : upLink(ROOT + "index.html", PAGE.title),
      filterInput(list, "Filter tables"), list);

    main.append(el("div", { class: "pagehead" },
      el("h1", {}, flat ? PAGE.title : DOC.name),
      el("div", { class: "sub" }, plural(DOC.tables.length, "table"))));
    main.append(sortableTable(
      [{ label: "Table", key: "name" }, { label: "Type", key: "type" }, { label: "Columns", key: "cols" }, { label: "Description" }],
      DOC.tables.map((t) => ({
        keys: { name: t.name, type: t.table_type || "", cols: t.column_count },
        cells: [tableLink(tid(t), t.name), typeChip(t.table_type), t.column_count, t.description || ""],
        data: t,
      })),
      STANDALONE ? null : (r) => { location.href = r.data.name + ".html"; }));
  }

  // --------------------------------------------------------------- table

  const TABLE_TABS = [["overview", "Overview"], ["sources", "Sources"]];
  const COLUMN_TABS = [["details", "Details"], ["lineage", "Lineage"], ["derivation", "Derivation"],
    ["usedby", "Used by"], ["validation", "Validation"]];
  const TAB_ALIASES = { diagram: "sources", columns: "overview" }; // older links

  function renderTable() {
    const G = DOC.lineage;
    const upstream = {};
    for (const e of G.edges) (upstream[e.target] = upstream[e.target] || []).push(e);
    const columnsByName = {};
    for (const c of DOC.columns) columnsByName[c.name] = c;
    const cid = (name) => DOC.id + "." + name;
    const sourceTables = (name) => new Set((G.leaf_summaries[cid(name)] || []).map((s) => s.table_id)).size;

    // --- crumbs: where you are (group ▸ table ▸ column)
    const tableCrumb = el("a", { href: "#" });
    const colCrumb = el("span");
    const colSep = sep();
    const crumbs = [];
    if (DOC.group) {
      crumbs.push(sep(), STANDALONE ? el("span", {}, DOC.group) : el("a", { href: "index.html" }, DOC.group));
    }
    crumbs.push(sep(), tableCrumb, colSep, colCrumb);
    tableCrumb.textContent = DOC.table;
    const { sidebar, main } = shell(crumbs);

    // --- sidebar
    const list = el("ul", { class: "navlist" });
    list.append(el("li", { class: "group" }, plural(DOC.columns.length, "column")));
    for (const c of DOC.columns) {
      const n = sourceTables(c.name);
      const li = el("li", { "data-name": c.name, "data-key": c.name },
        el("span", {}, c.name),
        el("span", { class: "badge" }, c.internal ? "internal"
          : DOC.table_type === "generated" ? plural(n, "source") : (c.source || "data")));
      li.addEventListener("click", () => go(c.name, state.colTab));
      list.append(li);
    }
    const up = el("div");
    sidebar.append(up, filterInput(list, "Filter columns"), list);

    const state = { col: null, tab: null, view: null, tableTab: "overview", colTab: "details" };
    function go(col, tab, view) { location.hash = hashFor(col, tab, view); }

    function readHash() {
      const raw = location.hash.slice(1);
      const legacy = /^col-(.+)$/.exec(raw); // old guidebook anchors
      const params = new URLSearchParams(legacy ? "col=" + legacy[1] : raw);
      const col = params.get("col");
      state.col = col && columnsByName[col] ? col : null;
      const tabs = (state.col ? COLUMN_TABS : TABLE_TABS).map((t) => t[0]);
      const tab = TAB_ALIASES[params.get("tab")] || params.get("tab");
      state.tab = tabs.includes(tab) ? tab : (state.col ? state.colTab : state.tableTab);
      state.view = params.get("view") === "diagram" || params.get("tab") === "diagram" ? "diagram" : "list";
      if (state.col) state.colTab = state.tab; else state.tableTab = state.tab;
    }

    let redraw = null;
    function render() {
      readHash();
      for (const li of list.querySelectorAll("li[data-key]")) {
        li.classList.toggle("active", li.dataset.key === (state.col || ""));
      }
      tableCrumb.href = "#" + hashFor(null, state.tableTab);
      colCrumb.textContent = state.col || "";
      colSep.hidden = !state.col;
      up.replaceChildren(state.col
        ? upLink("#" + hashFor(null, state.tableTab), DOC.table)
        : (STANDALONE ? "" : upLink("index.html", DOC.group || PAGE.title)));
      const activeLi = list.querySelector("li.active");
      if (activeLi) activeLi.scrollIntoView({ block: "nearest" });
      main.replaceChildren();
      redraw = null;
      if (state.col) renderColumn(columnsByName[state.col]);
      else renderTableView();
    }

    function tabBar(tabs, current, col, counts) {
      const bar = el("div", { class: "tabs", role: "tablist" });
      for (const [key, label] of tabs) {
        bar.append(el("button", {
          role: "tab", class: key === current ? "active" : null, "aria-selected": key === current ? "true" : "false",
          onclick: () => go(col, key),
        }, label, counts && counts[key] != null ? el("span", { class: "count" }, counts[key]) : null));
      }
      return bar;
    }

    // ---------- table view
    function renderTableView() {
      main.append(el("div", { class: "pagehead" },
        el("h1", {}, DOC.table, " ", typeChip(DOC.table_type)),
        el("div", { class: "sub" }, [DOC.group, plural(DOC.columns.length, "column"),
          DOC.location ? "source " + DOC.location.source_system : null].filter(Boolean).join(" · ")),
        DOC.description ? el("div", { class: "desc" }, DOC.description) : el("div", { class: "warn" }, "No table description.")));
      const sourceCount = new Set(Object.values(G.leaf_summaries).flat()
        .filter((s) => (G.tables[s.table_id] || {}).table_type !== "generated").map((s) => s.table_id)).size;
      main.append(tabBar(TABLE_TABS, state.tab, null, { sources: sourceCount }));
      const body = el("div");
      main.append(body);
      ({ overview: tableOverview, sources: tableSourcesTab })[state.tab](body);
    }

    function tableOverview(body) {
      body.append(kv([
        ["Type", typeChip(DOC.table_type)],
        ["Primary key", DOC.primary_key.length ? el("code", {}, DOC.primary_key.join(", ")) : null],
        ["Specification", DOC.source_file ? DOC.source_file + (DOC.source_sheet_name ? " · " + DOC.source_sheet_name : "") : null],
        ["Base table", DOC.base_table ? el("span", {}, tableLink(DOC.base_table),
          (G.tables[DOC.id] || {}).base_inferred ? " (inferred)" : "") : null],
        ["Base strategy", DOC.base_table_strategy],
        ["Union of", DOC.source_tables.length ? linkList(DOC.source_tables) : null],
        ["Union base tables", DOC.union_base_tables.length ? linkList(DOC.union_base_tables) : null],
        ["Final filter", DOC.final_filter ? el("pre", {}, DOC.final_filter) : null],
      ]));
      if (DOC.file) {
        const caps = Object.entries(DOC.file.captures || {});
        body.append(el("h2", {}, "Source"), kv([
          ["Kind", DOC.file.kind],
          ["Location (source system)", DOC.location ? el("code", {}, DOC.location.source_system) : null],
          ["Filename pattern", DOC.file.filename_regex ? el("code", {}, DOC.file.filename_regex) : null],
          ["Captured from name", caps.length ? caps.map(([g, n]) => g + " → " + n).join(", ") : null],
          ["Format", formatOf(DOC.file)],
        ]));
      }
      body.append(el("h2", {}, "Reads from"),
        DOC.upstream_tables.length ? linkList(DOC.upstream_tables) : empty("Reads directly from its source."));
      body.append(el("h2", {}, "Used by"),
        DOC.downstream_tables.length ? linkList(DOC.downstream_tables) : empty("No other table reads this table."));
      if (DOC.foreign_keys.length) {
        body.append(el("h2", {}, "Joins"), sortableTable(
          [{ label: "Column", key: "c" }, { label: "References" }, { label: "Join filter" }],
          DOC.foreign_keys.map((fk) => ({
            keys: { c: fk.column },
            cells: [el("code", {}, fk.column), tableLink(fk.references_table_id, fk.references_table_id + "." + fk.references_column, fk.references_column),
              fk.join_filter ? el("code", {}, fk.join_filter) : ""],
          }))));
      }
      if (DOC.table_rules.length) body.append(el("h2", {}, "Table rules"), rulesTable(DOC.table_rules));
      if ((G.warnings || []).length) {
        body.append(el("h2", {}, "Lineage warnings"), el("ul", {}, ...G.warnings.map((w) => el("li", { class: "warn" }, w))));
      }
    }

    function tableSourcesTab(body) {
      const toggle = el("div", { class: "segmented", role: "group", "aria-label": "Sources view" });
      for (const [key, label] of [["list", "List"], ["diagram", "Diagram"]]) {
        toggle.append(el("button", {
          class: state.view === key ? "active" : null, "aria-pressed": state.view === key ? "true" : "false",
          onclick: () => go(null, "sources", key === "list" ? null : key),
        }, label));
      }
      body.append(toggle);
      (state.view === "diagram" ? tableDiagram : tableSources)(body);
    }

    function tableSources(body) {
      const bySource = new Map();
      const noFile = [];
      for (const c of DOC.columns) {
        if (c.internal) continue;
        const leaves = G.leaf_summaries[cid(c.name)] || [];
        let hasFile = false;
        for (const s of leaves) {
          if ((G.tables[s.table_id] || {}).table_type === "generated") continue;
          hasFile = true;
          if (!bySource.has(s.table_id)) bySource.set(s.table_id, { columns: new Map(), feeds: new Set() });
          const g = bySource.get(s.table_id);
          if (!g.columns.has(s.column)) g.columns.set(s.column, { leaf: s, feeds: new Set() });
          g.columns.get(s.column).feeds.add(c.name);
          g.feeds.add(c.name);
        }
        if (!hasFile) noFile.push({ col: c, leaves });
      }
      const rows = [...bySource.entries()].sort((a, b) => {
        const la = (G.tables[a[0]].location || {}).source_system || "~";
        const lb = (G.tables[b[0]].location || {}).source_system || "~";
        return la.localeCompare(lb) || a[0].localeCompare(b[0]);
      });
      const systems = new Set(rows.map(([tid]) => (G.tables[tid].location || {}).source_system));
      const colCount = rows.reduce((n, [, g]) => n + g.columns.size, 0);
      const fed = DOC.columns.filter((c) => !c.internal).length - noFile.length;
      body.append(el("div", { class: "muted" }, plural(systems.size, "source system") + " · " + plural(rows.length, "source table") +
        " · " + plural(colCount, "source column") + " feed " + fed + " of " + (fed + noFile.length) + " columns"));
      const tbody = el("tbody");
      for (const [tid, g] of rows) {
        const t = G.tables[tid];
        const cols = [...g.columns.entries()].sort((a, b) => a[0].localeCompare(b[0]));
        const feeds = [...g.feeds].sort();
        tbody.append(el("tr", {},
          el("td", {}, (t.location || {}).source_system || "—"),
          el("td", {}, el("div", {}, tableLink(tid)), typeChip(t.table_type)),
          el("td", {}, t.file && t.file.filename_regex ? el("code", {}, t.file.filename_regex) : ""),
          el("td", {}, formatOf(t.file)),
          el("td", {}, details(plural(cols.length, "column"), cols.map(([name, info]) =>
            el("span", {}, tableLink(tid, name, name), " ",
              el("span", { class: "badge" }, leafLabel(G.columns[info.leaf.column_id]) + " → " + info.feeds.size))))),
          el("td", {}, details(plural(feeds.length, "column"), feeds.map((name) =>
            el("a", { href: "#" + hashFor(name, "lineage") }, name))))));
      }
      body.append(el("div", { class: "tablewrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["Source system", "Table", "Filename pattern", "Format", "Source columns", "Feeds"]
          .map((h) => el("th", {}, h)))), tbody)));
      if (noFile.length) {
        body.append(el("h2", {}, "Columns without a source table"),
          el("div", { class: "muted" }, "Literal defaults or values stamped at runtime."),
          sortableTable([{ label: "Column", key: "c" }, { label: "Value" }],
            noFile.map(({ col, leaves }) => ({
              keys: { c: col.name },
              cells: [el("a", { href: "#" + hashFor(col.name, "derivation") }, col.name),
                [...new Set(leaves.map((s) => leafLabel(G.columns[s.column_id])))].join("; ") || "—"],
            }))));
      }
    }

    function details(label, items) {
      const d = el("details", {}, el("summary", {}, label));
      d.append(el("ul", {}, ...items.map((i) => el("li", {}, i))));
      return d;
    }

    function tableDiagram(body) {
      body.append(el("div", { class: "muted" }, "Tables this table reads from, left to right. Click a table to open it."));
      const tUp = {};
      for (const e of G.edges) {
        const s = colOf(e.source)[0], t = colOf(e.target)[0];
        if (s === t) continue;
        (tUp[t] = tUp[t] || new Set()).add(s);
      }
      const upstreamOf = (id) => [...(tUp[id] || [])];
      const { ids, depth, max } = layerize(DOC.id, upstreamOf);
      const layers = [];
      for (let d = max; d >= 0; d--) layers.push([]);
      for (const id of ids.sort()) {
        const t = G.tables[id] || { id };
        const hdr = el("div", { class: "hdr" },
          el("div", { class: "name" }, tableLink(id, id)),
          el("div", { class: "loc" }, t.location ? "source " + t.location.source_system : (t.table_type || "table not found")));
        const card = el("div", { class: "tcard " + typeClass(t.table_type) + (id === DOC.id ? " current" : "") }, hdr);
        layers[max - depth[id]].push({ el: card, anchors: { [id]: card } });
      }
      for (const layer of layers) {
        layer.sort((a, b) => a.el.textContent.localeCompare(b.el.textContent));
      }
      const links = [];
      for (const [t, srcs] of Object.entries(tUp)) {
        if (!(t in depth)) continue;
        for (const s of srcs) links.push({ from: s, to: t, title: s + " → " + t });
      }
      const dag = el("div", { class: "dag" });
      body.append(dag);
      redraw = () => drawDag(dag, layers, links);
      redraw();
    }

    // ---------- column view
    function renderColumn(c) {
      const leaves = G.leaf_summaries[cid(c.name)] || [];
      main.append(el("div", { class: "pagehead" },
        el("h1", {}, c.name, " ", el("span", { class: "chip soft" }, c.data_type)),
        c.description ? el("div", { class: "desc" }, c.description) : el("div", { class: "warn" }, "No description.")));
      main.append(tabBar(COLUMN_TABS, state.tab, c.name, {
        lineage: new Set(leaves.map((s) => s.table_id)).size,
        derivation: c.candidates.length || null,
        usedby: c.used_by.length,
        validation: c.validations.length,
      }));
      const body = el("div");
      main.append(body);
      ({ details: columnDetails, lineage: columnLineage, derivation: columnDerivation, usedby: columnUsedBy,
        validation: columnValidation })[state.tab](body, c, leaves);
    }

    function columnDetails(body, c, leaves) {
      const nullable = c.nullable && typeof c.nullable === "object"
        ? Object.entries(c.nullable).map(([k, v]) => k + (v ? " nullable" : " required")).join(" · ")
        : (c.nullable === true ? "nullable" : c.nullable === false ? "required" : null);
      body.append(kv([
        ["Type", el("code", {}, c.data_type)],
        ["Format", c.format ? el("code", {}, c.format) : null],
        ["Length", c.length],
        ["Nullable", nullable],
        ["Kind", c.internal ? "internal helper" : c.source],
        ["Key", c.key_type],
        ["Canonical name", c.canonical_name],
        ["Default", c.default != null ? el("code", {}, c.default) : null],
        ["Provenance policy", c.provenance_policy],
        ["Provenance notes", c.provenance_notes],
        ["Examples", c.sample_values.length ? el("span", {}, ...c.sample_values.flatMap((v, i) => [i ? " " : "", el("code", {}, v)])) : null],
      ]));
    }

    function columnLineage(body, c, leaves) {
      const groups = new Map();
      for (const s of leaves) {
        if (!groups.has(s.table_id)) groups.set(s.table_id, []);
        groups.get(s.table_id).push(s);
      }
      const tbody = el("tbody");
      for (const [tid, ls] of groups) {
        const t = G.tables[tid] || {};
        const best = ls[0];
        const prio = (best.path_priority || [])[0];
        tbody.append(el("tr", {},
          el("td", {}, (prio == null || prio === UNSET ? "–" : prio) + " · " + plural(best.hops, "hop")),
          el("td", {}, best.source_system || "—"),
          el("td", {}, el("div", {}, tableLink(tid)), typeChip(t.table_type)),
          el("td", {}, ...ls.map((s) => el("div", {}, tableLink(tid, s.column, s.column), " ",
            el("span", { class: "badge" }, leafLabel(G.columns[s.column_id]))))),
          el("td", {}, best.filename_regex ? el("code", {}, best.filename_regex) : ""),
          el("td", {}, formatOf(t.file))));
      }
      body.append(el("h2", {}, "Ultimate sources"));
      body.append(leaves.length ? el("div", { class: "tablewrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["Best path", "Source system", "Table", "Columns", "Filename pattern", "Format"]
          .map((h) => el("th", {}, h)))), tbody)) : empty("Not traced."));

      body.append(el("h2", {}, "Path"),
        el("div", { class: "muted" }, "Data flows left to right. Click a line to see how that step is derived."));
      const dag = el("div", { class: "dag" });
      const detail = el("div");
      body.append(dag, detail);
      const target = cid(c.name);
      const upIds = (id) => (upstream[id] || []).map((e) => e.source);
      const { ids, depth, max } = layerize(target, upIds);
      const layerMaps = [];
      for (let d = max; d >= 0; d--) layerMaps.push(new Map());
      for (const id of ids) {
        const node = G.columns[id] || { id, table_id: colOf(id)[0], name: colOf(id)[1] };
        const m = layerMaps[max - depth[id]];
        if (!m.has(node.table_id)) m.set(node.table_id, []);
        m.get(node.table_id).push(node);
      }
      const layers = layerMaps.map((m) => [...m.entries()].sort((a, b) => {
        const la = (G.tables[a[0]].location || {}).source_system || "";
        const lb = (G.tables[b[0]].location || {}).source_system || "";
        return la.localeCompare(lb) || a[0].localeCompare(b[0]);
      }).map(([tid, cols]) => {
        const t = G.tables[tid] || {};
        const card = el("div", { class: "tcard " + typeClass(t.table_type) },
          el("div", { class: "hdr" }, el("div", { class: "name" }, tableLink(tid, tid)),
            el("div", { class: "loc" }, t.location ? "source " + t.location.source_system : (t.table_type || "table not found"))));
        const anchors = {};
        for (const n of cols.sort((a, b) => a.name.localeCompare(b.name))) {
          const href = tableHref(tid, n.name, "lineage");
          const row = el("div", { class: "row" + (n.id === target ? " target" : "") },
            href ? el("a", { href }, n.name) : n.name,
            n.leaf_kind ? el("span", { class: "kind" }, leafLabel(n)) : null);
          anchors[n.id] = row;
          card.append(row);
        }
        return { el: card, anchors };
      }));
      const links = [];
      for (const id of ids) {
        for (const e of upstream[id] || []) {
          links.push({
            from: e.source, to: e.target,
            title: e.kind + (e.priority != null ? " · priority " + e.priority : "") + (e.table_instance ? " · " + e.table_instance : ""),
            onclick: () => showEdge(detail, e),
          });
        }
      }
      redraw = () => drawDag(dag, layers, links);
      redraw();
    }

    function showEdge(detail, e) {
      detail.replaceChildren(el("h3", {}, e.source + " → " + e.target), kv([
        ["Kind", e.kind], ["Priority", e.priority], ["Table instance", e.table_instance],
        ["Via (join bridge)", e.via], ["Join filter", e.join_filter ? el("code", {}, e.join_filter) : null],
        ["Row filter", e.row_filter ? el("code", {}, e.row_filter) : null],
      ]), e.expression ? el("pre", {}, e.expression) : null);
    }

    function columnDerivation(body, c) {
      const strategy = c.derivation_strategy;
      if (strategy === "primary_key" || strategy === "base_column") {
        body.append(el("p", {}, strategy === "primary_key"
          ? "Primary key taken from the base view (the base table, or every union source)."
          : "Passed through from the base table: ", DOC.base_table ? tableLink(DOC.base_table, DOC.base_table, c.name) : null));
      }
      if (c.derivation_explanation_html) body.append(trusted(c.derivation_explanation_html));
      if (!c.candidates.length && !strategy) {
        body.append(empty(DOC.table_type === "generated"
          ? "No derivation: the column is " + (c.default != null ? "the literal " + c.default : "NULL") + "."
          : "No derivation: the value is read directly from the file" + (c.source === "filename" ? " name." : ".")));
      }
      for (const cand of c.candidates) {
        const src = cand.table_id
          ? tableLink(cand.table_id, cand.table_id + (cand.column ? "." + cand.column : ""), cand.column || null)
          : el("span", {}, "computed in this table");
        body.append(el("div", { class: "candidate" },
          el("div", { class: "head" }, el("span", { class: "chip" }, "Priority " + cand.priority), src,
            cand.table_instance ? el("span", { class: "chip soft" }, "as " + cand.table_instance) : null,
            cand.via ? el("span", { class: "chip soft" }, "via " + cand.via) : null),
          cand.join_filter ? el("div", { class: "filter" }, "Join filter ", el("code", {}, cand.join_filter)) : null,
          cand.row_filter ? el("div", { class: "filter" }, "Row filter ", el("code", {}, cand.row_filter)) : null,
          cand.expression ? el("pre", {}, cand.expression) : null,
          cand.reason_html ? trusted(cand.reason_html) : null));
      }
      if (c.survivorship) {
        const s = c.survivorship;
        body.append(el("h2", {}, "Survivorship"), el("div", {}, el("span", { class: "chip" }, s.strategy)));
        if (s.explanation_html) body.append(trusted(s.explanation_html));
        body.append(kv([["Default value", s.default_value != null ? el("code", {}, s.default_value) : null],
          ["Default when", s.default_condition ? el("code", {}, s.default_condition) : null]]));
      }
    }

    function columnUsedBy(body, c) {
      if (!c.used_by.length) { body.append(empty("No other column reads this column.")); return; }
      const byTable = new Map();
      for (const ref of c.used_by) {
        const [tid, name] = colOf(ref.column_id);
        if (!byTable.has(tid)) byTable.set(tid, []);
        byTable.get(tid).push([name, ref.via]);
      }
      for (const [tid, refs] of [...byTable.entries()].sort()) {
        body.append(el("h3", {}, tableLink(tid)), el("div", { class: "linklist" },
          ...refs.sort().map(([n, via]) => el("span", {}, tableLink(tid, n, n, "lineage"),
            via === "fk" ? el("span", { class: "badge" }, " via fk") : null))));
      }
    }

    function columnValidation(body, c) {
      body.append(c.validations.length ? rulesTable(c.validations) : empty("No validation rules."));
    }

    // keyboard: ↑/↓ (or j/k) move through the sidebar
    document.addEventListener("keydown", (ev) => {
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
      const down = ev.key === "ArrowDown" || ev.key === "j", up = ev.key === "ArrowUp" || ev.key === "k";
      if (!down && !up) return;
      const items = [...list.querySelectorAll("li[data-key]")].filter((li) => !li.hidden);
      const i = items.findIndex((li) => li.classList.contains("active"));
      const next = items[Math.min(items.length - 1, Math.max(0, i + (down ? 1 : -1)))];
      if (!next) return;
      ev.preventDefault();
      go(next.dataset.key || null, next.dataset.key ? state.colTab : state.tableTab);
    });

    window.addEventListener("hashchange", render);
    let timer = null;
    window.addEventListener("resize", () => {
      clearTimeout(timer);
      timer = setTimeout(() => { if (redraw) redraw(); }, 150);
    });
    render();
  }

  function rulesTable(rules) {
    return sortableTable(
      [{ label: "Rule", key: "type" }, { label: "Severity", key: "sev" }, { label: "Description" }, { label: "Parameters" }],
      rules.map((r) => ({
        keys: { type: r.type, sev: r.severity },
        cells: [el("code", {}, r.type), r.severity, r.description || "",
          r.kwargs ? el("code", {}, JSON.stringify(r.kwargs)) : ""],
      })));
  }

  ({ home: renderHome, group: renderGroup, table: renderTable })[PAGE.kind]();
})();
