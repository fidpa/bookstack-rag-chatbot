# Widget Integration

How to embed the chat widget into BookStack — and, with small adjustments, into any other site.

## Embedding into BookStack (the default path)

BookStack supports injecting custom HTML into the `<head>` of every page.

1. Sign in to BookStack as an admin.
2. Go to **Settings → Customisation**.
3. Find the section **Custom HTML head content**.
4. Paste the entire content of [`bookstack-integration/widget.html`](../bookstack-integration/widget.html).
5. Click **Save Settings**.

Reload any wiki page. The chat bubble appears in the lower-right corner.

> **Where does the widget call?** The default JavaScript posts to `/chat/api/widget` (relative URL). If your BookStack is on a different host than the chatbot backend, see [Cross-host setup](#cross-host-setup) below.

## Configuration

The widget exposes a global `window.KnowledgeBotChat` object you can configure **before** the bubble is created:

```html
<script>
  window.KnowledgeBotChat = window.KnowledgeBotChat || {};
  window.KnowledgeBotChat.config = {
    position:      'bottom-right',      // 'bottom-right' | 'bottom-left'
    accent:        '#0a84ff',           // CSS colour
    startMessage:  'Hi! Ask me about anything in this wiki.',
    apiBase:       '/chat/api',         // relative or absolute base URL
    placeholder:   'Type a question…',
    closeLabel:    'Close',
  };
</script>
<!-- then paste widget.html here -->
```

All keys are optional. Defaults are baked into `widget.html`.

## Cross-host Setup

If BookStack runs on `wiki.example.com` and the chatbot runs on `chatbot.example.com`, you need to:

### 1. Reverse-proxy `/chat/api/` from BookStack

This keeps the widget call same-origin and avoids CORS headaches. Example nginx snippet:

```nginx
location /chat/api/ {
    proxy_pass http://chatbot.internal:8888/chat/api/;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

There is a starter template at [`docker/nginx-example.conf`](../docker/nginx-example.conf).

### 2. Make sure the chatbot trusts the proxy headers

By default the chatbot uses the source IP of the inbound TCP connection — which will be the proxy's IP, not the visitor's. To fix:

- In `.env`, set `IP_ACCESS_CONTROL=false` if you trust the network entirely.
- Or extend the IP allow-list logic in `chatbot/utils/` to read `X-Forwarded-For` after stripping the trusted proxy IP. (PRs welcome.)

## Embedding Elsewhere

The widget is vanilla HTML/CSS/JS — no build step. To embed it in Wiki.js, Outline, a static site, or a custom app:

1. Copy `bookstack-integration/widget.html` somewhere your site can serve it.
2. In each page where you want the widget, include the file:

```html
<!-- at the end of <body> -->
<script src="/assets/widget.html" type="text/html"></script>
<script>
  // load widget.html as text, evaluate the script blocks
  fetch('/assets/widget.html').then(r => r.text()).then(html => {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html;
    document.body.appendChild(wrapper);
  });
</script>
```

This is the most flexible option, but it requires that your site serve the file from the same origin as the chatbot API (or that you set up the reverse-proxy above).

## Hiding the Widget on Specific Pages

The widget respects a `data-knowledgebot-disabled` attribute on `<body>`:

```html
<body data-knowledgebot-disabled="true">
  ...
</body>
```

In BookStack, you can also wrap the script in a check:

```html
<script>
  if (location.pathname.includes('/admin')) {
    /* don't load the widget */
  } else {
    /* load widget.html */
  }
</script>
```

## Multi-Language Widget

The default labels are English. Override them via the config object:

```js
window.KnowledgeBotChat.config = {
  startMessage: 'Hallo! Stelle mir eine Frage zum Wiki.',
  placeholder:  'Frage tippen…',
  closeLabel:   'Schließen',
};
```

The chatbot itself answers in whatever language the user types in, as long as the underlying LLM supports it (all three default providers do for common languages).

## Styling

The widget ships with a small set of CSS variables you can override:

```css
:root {
  --kb-accent:        #0a84ff;
  --kb-bubble-bg:     #ffffff;
  --kb-bubble-text:   #1a1a1a;
  --kb-user-bg:       #0a84ff;
  --kb-user-text:     #ffffff;
  --kb-bot-bg:        #f1f3f5;
  --kb-bot-text:      #1a1a1a;
}
```

For dark mode, swap these via `prefers-color-scheme` or a JS toggle.

## Removing the Widget

In BookStack: clear the **Custom HTML head content** field and save. The widget vanishes on the next page load.
