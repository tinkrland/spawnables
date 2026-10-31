# email

the agent's own mailbox, and the only lane that has to work while the machine is
off. the provider catches the mail (agentmail or carlyemail: 1000 messages and
three inboxes on custom domains per month), so an idle host still has mail waiting
when it wakes.

wired: the front door. two schemes, one of them good: svix (`whsec_` secret,
`webhook-id`/`webhook-timestamp`/`webhook-signature` over `id.timestamp.body`, so
the body is covered and the signature expires), or a plain shared header for a
provider that only offers that. then a sender whitelist, because an invite from a
stranger is not work.

not wired: sending. relay is narrow on purpose and runs through `SMTP_URL` only.

gate: `CARLYEMAIL_SIGNING_SECRET` (svix) or `HEYPHONY_MAIL_SECRET` (plain), plus
`HEYPHONY_FORWARD_WHITELIST` and `SMTP_URL`. unset closes the lane.
