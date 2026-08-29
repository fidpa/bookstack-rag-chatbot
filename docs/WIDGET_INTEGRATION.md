# Widget Integration

How to embed the chat widget into BookStack, and what it takes to put it anywhere else.

`bookstack-integration/widget.html` is a single self-contained fragment: one `<style>`
block, one `<script>` block, no build step and no external assets. There is no
`widget.js`; everything is inline.

## Embedding into BookStack (the default path)

BookStack can inject custom HTML into the `<head>` of every page.

1. Sign in to BookStack as an admin.
2. Go to **Settings → Customisation**.
3. Find the section **Custom HTML head content**.
4. Paste the entire content of [`bookstack-integration/widget.html`](../bookstack-integration/widget.html).
5. Click **Save Settings**.

Reload any wiki page. The chat bubble appears in the lower-right corner.

## Where the widget sends its requests

`getApiUrl()` decides at load time, from `window.location`, and nothing overrides it:

- On `localhost`, `127.0.0.1` or `::1`, it posts to `http://<hostname>:8888/chat/api/widget`,
  the chatbot's published port.
- Anywhere else, it posts to `<protocol>//<hostname>/chat/api/widget`, same-origin, and
  expects a reverse proxy to forward `/chat/api/` to the chatbot.

Both branches log the chosen URL to the browser console under `[Widget]`, which is the
quickest way to see what it decided.

## Configuration: there is none yet

The widget takes no configuration object. `widget.html` **assigns**
`window.KnowledgeBotChat = { … }` at load time, so anything set on that global
beforehand is overwritten rather than read. Position, accent colour, greeting,
placeholder and API base are literals in the file.

To change any of them, edit `widget.html` before pasting it:

| What | Where in `widget.html` |
|---|---|
| Bubble position | `.kb-chat-button` `bottom: 20px; right: 20px` near the top, and `right: 20px` on the panel |
| Accent colour | The gradient `linear-gradient(135deg, #206ea7 0%, #1b5a8c 100%)`, which recurs in the button, header and send button |
| Header title | `<h3>🤖 Chatbot</h3>` in the `kb-chat-header` markup |
| Greeting | The `Welcome!` block in `kb-chat-messages` |
| Input placeholder | `placeholder="Type your question..."` |
| API URL | `getApiUrl()` |

There are no `--kb-*` CSS custom properties to override, and no
`data-knowledgebot-disabled` attribute; both would be reasonable additions and neither
exists today. The styles are scoped under the `kb-` class prefix, so a stylesheet loaded
after the widget can restyle it without touching the file. PRs that turn the literals
into a real config object are welcome.

## Cross-host Setup

If BookStack runs on `wiki.example.com` and the chatbot elsewhere, the widget's
same-origin branch means a reverse proxy is not one option among several; it is the
only one.

### 1. Proxy `/chat/api/` from the BookStack host

```nginx
location /chat/api/ {
    proxy_pass http://chatbot.internal:8888/chat/api/;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

A starter template is at [`docker/nginx-example.conf`](../docker/nginx-example.conf).

### 2. Decide what the allow-list sees

`_client_ip()` in `chatbot/utils/rate_limiter.py` reads the first entry of
`X-Forwarded-For` when the header is present, and falls back to `REMOTE_ADDR`. With the
proxy config above, `ALLOWED_VPN_IPS` therefore matches the **visitor's** IP, not the
proxy's, and the per-IP rate limit counts per visitor.

The flip side is that the header is trusted as sent. If the proxy is reachable from the
public internet, it has to strip inbound `X-Forwarded-For` before setting its own, or
anyone can name their own source IP. See [SECURITY.md](SECURITY.md).

## Embedding Elsewhere

The fragment is plain HTML, CSS and JS, so Wiki.js, Outline, a static site or a custom
app can all carry it. Two constraints travel with it:

- The API URL is derived from `window.location`, so the host page has to be same-origin
  with the chatbot, or sit behind the proxy above.
- The chatbot has no auth of its own beyond the IP allow-list, so whatever fronts the
  host page is what protects the chatbot too.

Paste the fragment into your template's `<head>` or before `</body>`. Loading it at
runtime through `fetch()` and `innerHTML` does **not** work: `innerHTML` inserts
`<script>` elements without executing them. If you must load it dynamically, insert the
markup, then recreate each `<script>` node with `document.createElement('script')` and
copy its text content across.

## Hiding the Widget on Specific Pages

The widget has no opt-out hook, so this happens in the host page. In BookStack, the
Custom HTML head content is one field applied everywhere; to scope it, wrap the
`<script>` block from `widget.html` in a guard that returns before `init()` runs:

```html
<script>
  if (!location.pathname.startsWith('/settings')) {
    /* the widget's own script block goes here */
  }
</script>
```

## Language

Widget labels are English literals in `widget.html`; translating them means editing the
file. The answers are a different matter: the default system prompt in
`chatbot/chat/widget_service.py` ends with "Respond in the same language the user writes
in", so the bot follows the user as far as the configured model can. Override the whole
prompt with `CHATBOT_SYSTEM_PROMPT` if you want it pinned to one language.
