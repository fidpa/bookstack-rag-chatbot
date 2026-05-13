# Acme Widget v3 — Customer FAQ

*For external use. Last updated: 2026-03-10.*

The Acme Widget is Acme Inc.'s flagship product. The Widget is a small embeddable HTML/JavaScript component that lets web applications add live customer-facing chat without running a chat server. This page collects the questions our support team gets asked most often.

## Getting started

### What does the Widget do?

It adds a chat bubble to any website. Visitors can type a question; the question is routed to a queue of human agents (your team) or to a configured LLM provider. The Widget handles message persistence, file uploads, and offline routing.

### How do I install the Widget on my site?

Add this snippet just before `</body>` on every page you want the Widget on:

```html
<script async defer
  src="https://cdn.example.com/widget/v3/widget.js"
  data-acme-key="YOUR_PUBLIC_KEY">
</script>
```

Replace `YOUR_PUBLIC_KEY` with the key shown in your Acme dashboard under Settings → API Keys. The Widget appears in the lower-right corner of every page where the script loads.

### Which browsers does the Widget support?

The current Widget (v3) supports:

- Chrome / Edge 105 and newer
- Firefox 102 and newer
- Safari 15.6 and newer

The Widget will not load on Internet Explorer 11. We dropped IE11 support in v2.4.

## Configuration

### Can I change the colours and position?

Yes. Pass `data-acme-config` with a JSON string:

```html
<script async defer
  src="https://cdn.example.com/widget/v3/widget.js"
  data-acme-key="YOUR_PUBLIC_KEY"
  data-acme-config='{"position":"bottom-left","accent":"#0a84ff"}'>
</script>
```

Supported configuration keys: `position`, `accent`, `language`, `start_message`, `business_hours`.

### Does the Widget support webhooks?

Yes. The Widget posts events to your endpoint as JSON `POST` requests. Configure the endpoint in the Acme dashboard under Settings → Webhooks. The events are:

- `message.received` — visitor sent a message
- `message.sent` — your agent sent a reply
- `conversation.started` — visitor opened the Widget for the first time in the session
- `conversation.closed` — visitor or agent closed the conversation
- `file.uploaded` — visitor attached a file

All webhook payloads are signed with an HMAC-SHA256 header `X-Acme-Signature`. The signing secret is unique per webhook endpoint.

### Can I disable the Widget on specific pages?

Add `data-acme-disabled="true"` to the script tag, or call `window.AcmeWidget.hide()` from your own JavaScript.

## Pricing and limits

### How is the Widget priced?

By **monthly active conversations** (MACs). One MAC = one visitor who opens the Widget at least once in a calendar month.

- Starter: USD 49 / month, up to 500 MACs
- Growth: USD 199 / month, up to 5 000 MACs
- Enterprise: custom

### What happens if I exceed my plan?

The Widget continues to function. We notify you by email after 100 % and 110 % of your plan; at 125 % you are auto-upgraded to the next tier on the next billing cycle.

### Is there a free tier?

Yes, up to 100 MACs per month. No credit card required.

## Data and privacy

### Where is the data stored?

EU customers' data is stored in `eu-central-1` (Frankfurt). US customers' data is stored in `us-east-1` (Virginia). Customers choose at signup.

### Is the Widget GDPR-compliant?

Yes. We are joint controller with you for visitor messages and provide a DPA on request from `legal@example.com`.

### Can I export and delete conversations?

Yes. Both are available from the Acme dashboard. The export is JSON. Deletion is irreversible and propagates to backups within 30 days.

## Troubleshooting

### The Widget icon doesn't appear

1. Open the browser developer console. Look for errors from `widget.js`.
2. Confirm your `data-acme-key` is correct (it's case-sensitive).
3. Check that your domain is on the allow-list in Settings → Domains.
4. Confirm there is no Content Security Policy blocking `cdn.example.com`.

### Visitors get "Service unavailable"

Either all your agents are offline and your business-hours configuration is set to refuse messages, or your account is suspended for non-payment. Check the dashboard banner first.

### Mobile keyboard hides the input

Known issue on iOS Safari with viewport heights below 600 px. Fix shipped in v3.4.1 (March 2026). Make sure `widget.js` is requested without an explicit version pin.
