# Acme Inc. IT Onboarding

*For new employees and contractors. Last updated: 2026-02-03.*

This page walks you through the IT setup you need to complete on day one. Plan about half a day for it. If you get stuck, post in `#it-help` on Slack — the IT team is on EU and US working hours.

## Before Your Start Date

A few things happen before you officially join:

- People sends you a welcome email with your Acme email address (`firstname.lastname@example.com`).
- IT ships you a company laptop. Default is a 14-inch MacBook Pro M-series. If you need Linux or a Windows machine, mention it in the offer-acceptance form.
- You receive a temporary password for your Acme account by SMS to the phone number on your contract.

If you have not received your laptop two days before your start date, email `it-shipping@example.com`.

## Day One Checklist

Work through these in order.

### 1. Power on and update

Sign in with the temporary password. The laptop will prompt you to:

1. Change the password (16 characters or more, mix of types).
2. Enable FileVault / BitLocker / LUKS for full-disk encryption.
3. Install pending macOS / Windows / Ubuntu updates.

### 2. Set up your Acme identity

1. Open `https://sso.example.com` and sign in with your Acme email and the new password.
2. Enrol two-factor authentication. Use the Acme-provided YubiKey if you received one; otherwise install the Authy app and scan the QR code.
3. Print or save the backup codes. Store them somewhere not on the laptop.

### 3. Install required tools

The IT team has prepared an installer at `https://intranet.example.com/onboarding/installer`. Run it. It installs:

- 1Password (password manager — you will receive an invite to the company vault).
- Slack.
- Zoom.
- Your team's IDE of choice (VS Code or JetBrains Toolbox).
- Browser extensions for 1Password and the company SSO.

### 4. Request your laptop budget items

Use the `#it-help` channel or the form at `https://intranet.example.com/orders` to request:

- External monitor (up to one).
- Keyboard and mouse.
- Headset.
- Docking station, if applicable.

All items are charged against your equipment budget (see the Employee Handbook).

### 5. Access requests

By default you get:

- Email and calendar.
- Slack.
- BookStack (this wiki).
- The shared Drive.

You will need to request access separately to:

- Source-code repositories (ask your manager).
- Production systems (PRs to the access-management repo, reviewed by Security).
- Financial systems (request through Finance).

## Common Issues

### "I can't sign in to SSO"

Most likely your temporary password has expired (they expire after 5 days). Email `it-help@example.com` from your personal email with proof of identity and we will reset it.

### "1Password vault is empty"

The invite is sent the morning of your start date. If it has not arrived by 10:00 local time, ping `#it-help`.

### "My YubiKey doesn't work"

Try a different USB port and a different cable. If still nothing, IT can mail you a replacement same-day for EU/US addresses.

### "I need admin / sudo rights on my laptop"

Engineering roles get admin by default. Other roles can request elevated rights with a justification in the form at `https://intranet.example.com/admin-rights`.

## Security Reminders

- **Never** share your laptop password or 2FA codes.
- Lock your screen when you step away (`Ctrl/Cmd + L`).
- Keep your laptop with you when travelling; if you must leave it in a hotel, lock it in the room safe.
- Report a lost or stolen device to `security@example.com` immediately, even at 03:00.
- Phishing simulations happen quarterly. Failing one is fine; ignoring one is not.

## Getting Help

| Topic | Channel | Email |
|---|---|---|
| General IT help | `#it-help` | `it-help@example.com` |
| Security / lost device | `#security` | `security@example.com` |
| Laptop shipping | — | `it-shipping@example.com` |
| Network / VPN | `#it-help` | `it-help@example.com` |
