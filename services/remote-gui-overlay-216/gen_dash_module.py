#!/usr/bin/env python3
"""
Generate the IEMS plugin's dashboard module from the live IEMS dashboard.

Reads the HTML the standalone dashboard serves, and emits a single ES module
that the remote-gui plugin page mounts.  Generating it rather than re-writing
it by hand is deliberate: the plugin then renders the same markup, the same
stylesheet and the same chart/controller logic the dashboard has been running,
so the two cannot drift visually or behaviourally.

Three transforms are applied:

  1.  The stylesheet is scoped.  Every selector is prefixed with the plugin
      root class, and the page-level selectors (:root, html, body, the
      universal reset) are rewritten onto that root, so nothing leaks into the
      surrounding remote-gui shell.
  2.  The markup is taken verbatim, minus its script tags.
  3.  The controller is wrapped in mountIemsDashboard(root, apiBase).  Inside
      that wrapper, document/fetch/setTimeout/setInterval are shadowed so DOM
      lookups are scoped to the plugin root, same-origin dashboard calls are
      routed through the plugin's proxy routes, and every timer can be torn
      down when React unmounts the page.

Usage: gen_dash_module.py <dashboard-url> <output.js>
"""

import json
import re
import sys
import urllib.request

ROOT = ".iems-dash-root"

# Names the wrapper shadows.  If the upstream controller ever declares one of
# these itself the shadowing would break silently, so we fail the build loudly.
SHADOWED = ["fetch", "setTimeout", "setInterval", "clearTimeout",
            "clearInterval", "document"]


# ── CSS scoping ──────────────────────────────────────────────────────────────
#
# A hand-rolled scanner rather than a regex split.  The stylesheet's very first
# rule is an @import whose url() contains semicolons (font weights), and a
# scanner that stops at the first ';' cuts it in half and then reads the
# remainder as a selector.  So every scan below steps over strings, comments
# and parenthesised values.

def _end_string(css, i):
    quote = css[i]
    i += 1
    n = len(css)
    while i < n:
        if css[i] == "\\":
            i += 2
            continue
        if css[i] == quote:
            return i + 1
        i += 1
    return i


def _end_paren(css, i):
    depth = 0
    n = len(css)
    while i < n:
        c = css[i]
        if c in "\"'":
            i = _end_string(css, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def _end_block(css, i):
    depth = 0
    n = len(css)
    while i < n:
        if css.startswith("/*", i):
            k = css.find("*/", i)
            i = n if k < 0 else k + 2
            continue
        c = css[i]
        if c in "\"'":
            i = _end_string(css, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def split_css(css):
    """Split a stylesheet into top-level chunks."""
    chunks, i, n, start = [], 0, len(css), None
    while i < n:
        if css.startswith("/*", i):
            k = css.find("*/", i)
            i = n if k < 0 else k + 2
            continue
        c = css[i]
        if start is None:
            if c.isspace():
                i += 1
                continue
            start = i
        if c in "\"'":
            i = _end_string(css, i)
            continue
        if c == "(":
            i = _end_paren(css, i)
            continue
        if c == ";":
            chunks.append(("at-simple", css[start:i + 1].strip()))
            start = None
            i += 1
            continue
        if c == "{":
            head = css[start:i].strip()
            j = _end_block(css, i)
            body = css[i + 1:j]
            chunks.append(("at-block" if head.startswith("@") else "rule",
                           head, body))
            start = None
            i = j + 1
            continue
        i += 1
    return chunks


def scope_selector(sel):
    s = sel.strip()
    if not s:
        return None
    if s in (":root", "html", "body"):
        return ROOT
    if s == "*":
        # The reset has to reach the root itself as well as its descendants.
        return ROOT + "," + ROOT + " *"
    if s.startswith("::") or s.startswith("*::"):
        return ROOT + " " + s
    return ROOT + " " + s


def scope_rules(chunks, out):
    for chunk in chunks:
        kind = chunk[0]
        if kind == "at-simple":
            continue  # @import is hoisted separately
        if kind == "at-block":
            _, head, body = chunk
            low = head.lower()
            if low.startswith("@keyframes") or low.startswith("@-webkit-keyframes") \
                    or low.startswith("@font-face"):
                out.append("%s{%s}" % (head, body))
            else:
                inner = []
                scope_rules(split_css(body), inner)
                out.append("%s{%s}" % (head, "\n".join(inner)))
            continue
        _, sel, body = chunk
        parts, seen = [], set()
        for one in sel.split(","):
            scoped = scope_selector(one)
            if scoped and scoped not in seen:
                seen.add(scoped)
                parts.append(scoped)
        if parts:
            out.append("%s{%s}" % (",".join(parts), body))


# The dashboard is a whole page, so it sizes itself against the viewport.  Inside
# the GUI it is a panel below a header and beside a sidebar, and 100vh there is
# always taller than the space it has, which leaves a scrollbar on a page that
# fits.  This is the only declaration changed from the original.
CONTAINER_FIT = """
/* container adaptation: the only rule that differs from the standalone page */
%s{min-height:100%%}
""" % ROOT


def scope_css(css):
    chunks = split_css(css)
    imports = [c[1] for c in chunks
               if c[0] == "at-simple" and c[1].lower().startswith("@import")]
    body = []
    scope_rules(chunks, body)
    return "\n".join(imports + body) + CONTAINER_FIT


def verify_scoped(css):
    """Every rule must be scoped, or the plugin repaints the whole GUI."""
    leaked = []
    for chunk in split_css(css):
        if chunk[0] == "rule":
            for one in chunk[1].split(","):
                one = one.strip()
                if one and not one.startswith(ROOT):
                    leaked.append(one)
        elif chunk[0] == "at-block":
            head = chunk[1].lower()
            if head.startswith("@media") or head.startswith("@supports"):
                leaked.extend(verify_scoped(chunk[2]))
    return leaked


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    url, out_path = sys.argv[1], sys.argv[2]
    html = urllib.request.urlopen(url, timeout=60).read().decode("utf-8")

    styles = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)
    if not styles:
        sys.exit("no <style> block found in dashboard HTML")
    css = scope_css("\n".join(styles))

    leaked = verify_scoped(css)
    if leaked:
        sys.exit("these selectors escaped scoping and would restyle the whole "
                 "GUI: %s" % ", ".join(leaked[:12]))

    scripts = [s for s in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
               if s.strip()]
    if len(scripts) != 1:
        sys.exit("expected exactly one non-empty <script> block, found %d"
                 % len(scripts))
    controller = scripts[0]

    for name in SHADOWED:
        if re.search(r"\b(?:const|let|var|function)\s+%s\b" % name, controller):
            sys.exit("upstream controller declares '%s', which the wrapper "
                     "shadows -- refusing to generate a silently broken module"
                     % name)

    body = re.search(r"<body[^>]*>(.*?)</body>", html, re.S)
    if not body:
        sys.exit("no <body> found in dashboard HTML")
    markup = re.sub(r"<script[^>]*>.*?</script>", "", body.group(1),
                    flags=re.S).strip()

    module = HEADER % (json.dumps(css), json.dumps(markup)) + controller + FOOTER

    with open(out_path, "w") as fh:
        fh.write(module)

    rules = sum(1 for c in split_css(css) if c[0] == "rule")
    print("generated %s" % out_path)
    print("  css     %6d bytes, %d rules, all scoped to %s"
          % (len(css), rules, ROOT))
    print("  markup  %6d bytes" % len(markup))
    print("  logic   %6d bytes" % len(controller))
    print("  module  %6d bytes" % len(module))


HEADER = '''// GENERATED by gen_dash_module.py from the live IEMS dashboard. Do not edit.
//
// Exports the dashboard's stylesheet, markup and controller as a mountable
// module.  The controller below is the dashboard's own code, unmodified; the
// wrapper around it scopes DOM access to the plugin root, routes the
// dashboard's same-origin /api calls through the plugin's proxy, and makes
// every timer cancellable so React can unmount the page cleanly.

export const DASH_CSS = %s;

export const DASH_HTML = %s;

const STYLE_ID = 'iems-dash-style';

export function injectDashStyle() {
  if (typeof window === 'undefined') return;
  if (window.document.getElementById(STYLE_ID)) return;
  const el = window.document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = DASH_CSS;
  window.document.head.appendChild(el);
}

export function mountIemsDashboard(__root, __apiBase) {
  const __base = String(__apiBase || '').replace(/\\/+$/, '');

  // The dashboard talks to its own server on same-origin /api/*, and to the
  // IEMS engine on an absolute /iems/* URL.  Both are re-pointed at this
  // plugin's routes, which forward to the real services on this host.
  const __api = (u) => {
    if (typeof u !== 'string') return u;
    if (/^https?:\\/\\//i.test(u)) {
      const m = u.match(/^https?:\\/\\/[^/]+(\\/iems\\/.*)$/i);
      return m ? __base + m[1] : u;
    }
    if (u.startsWith('/api/')) return __base + '/iems/dash' + u;
    if (u.startsWith('/iems/')) return __base + u;
    return u;
  };

  let __dead = false;
  const __timers = new Set();
  const __intervals = new Set();

  // A fetch that resolves after React has unmounted the page would run the
  // dashboard's own .then handler against a root that no longer exists.  Some
  // of these calls take twenty seconds, which is plenty of time for a user to
  // click away, so a settled-after-death promise is left permanently pending
  // instead: the continuation never runs and the closure is collected.
  const fetch = (u, o) => {
    if (__dead) return new Promise(() => {});
    return window.fetch(__api(u), o).then((r) => (__dead ? new Promise(() => {}) : r));
  };

  const setTimeout = (fn, ms) => {
    const id = window.setTimeout(() => {
      __timers.delete(id);
      if (!__dead) fn();
    }, ms);
    __timers.add(id);
    return id;
  };
  const setInterval = (fn, ms) => {
    const id = window.setInterval(() => { if (!__dead) fn(); }, ms);
    __intervals.add(id);
    return id;
  };
  const clearTimeout = (id) => { __timers.delete(id); window.clearTimeout(id); };
  const clearInterval = (id) => { __intervals.delete(id); window.clearInterval(id); };

  const __esc = (id) => (window.CSS && window.CSS.escape)
    ? window.CSS.escape(id) : id;

  // Scope the four lookups to the plugin root and forward everything else to
  // the real document, correctly bound. An earlier version listed only the
  // lookups, so document.createElement threw inside the plugin and any code
  // that built nodes -- the Ask tab's preset buttons, for one -- died silently
  // while the rest of the page carried on looking fine.
  const __realDoc = window.document;
  const __scoped = {
    getElementById: (id) => __root.querySelector('#' + __esc(id)),
    querySelector: (s) => __root.querySelector(s),
    querySelectorAll: (s) => __root.querySelectorAll(s),
    body: __root,
  };
  const document = new Proxy(__realDoc, {
    get(target, prop) {
      if (Object.prototype.hasOwnProperty.call(__scoped, prop)) return __scoped[prop];
      const value = target[prop];
      return typeof value === 'function' ? value.bind(target) : value;
    },
    set(target, prop, value) { target[prop] = value; return true; },
  });

  // ── begin dashboard controller (verbatim) ──────────────────────────────
'''

FOOTER = '''
  // ── end dashboard controller ───────────────────────────────────────────

  return function unmount() {
    __dead = true;
    __timers.forEach((id) => window.clearTimeout(id));
    __intervals.forEach((id) => window.clearInterval(id));
    __timers.clear();
    __intervals.clear();
    try { delete window.ackRec; } catch (e) { window.ackRec = undefined; }
  };
}
'''


if __name__ == "__main__":
    main()
