# attachments: what a message can put on disk, and what it can make the agent open

short version: an audio attachment from a carrier voicemail is written to one folder; nothing else is
written, nothing is executed, and nothing in a message can point the agent at a file outside that folder.

## per channel, what arrives

| channel | what actually travels | what this package does with it |
| --- | --- | --- |
| sms on a sip did | text only. sms does not ride sip, so the provider posts or emails it, and mms is not delivered by any vendor in the table in a way worth pretending about | stored as text. a link stays a link |
| voicemail (carrier email) | an audio attachment with a filename nobody chose, a transcript sometimes in the body | audio written to the voicemail folder as `<epoch>-<stem>-<sha8>.<audio suffix>`; the sender, seconds and any transcript become a `<name>.json` sidecar |
| a call | audio is a stream, not a file. recording is the client's job, not this package's | nothing written; the call log row is read from the client's sqlite |
| imessage, whatsapp, slack, discord, telegram | media exists on those rails, but they belong to the umbrella lanes | heyphony never reads their media. one lane owns one carrier means one place a file can come from |
| email | any attachment a person sends | when it is audio, the same voicemail path above. anything else is recorded as a name and a byte count, and left alone |

## how it is interpreted

- **audio**: played by a local player, or read by a human. a transcript is used only if the carrier
  sent one. no transcript means the field is null, never a guess made by this package.
- **anything else**: not decoded, not opened, not OCR'd, not handed to a model, not executed. a pdf is a
  row with a name.
- the interpretation that does happen to voicemail is textual: the carrier's transcript arrives through
  the email lane, so it is already the same untrusted text as any other message body.

## the risk, stated as the rule that answers it

the question worth asking is not "does it handle attachments" but "can a message make the agent open
some file anywhere on this machine". the answer is one directory, and four checks:

1. **one folder.** audio lands in `HEYPHONY_VOICEMAIL_DIR` (default `~/.local/share/.../voicemail`).
   `_attachments` sanitises the name to `[a-z0-9-]`, appends a content hash, and writes nothing outside
   that folder, so `../../evil.sh` becomes a wav in the voicemail folder and not a script in your home.
2. **an allowlisted suffix.** a part that claims `audio/mpeg` and names itself `evil.sh` used to keep the
   suffix. it does not any more: the suffix comes from the audio list or becomes `.wav`.
3. **a size cap.** 25 mb. a carrier voicemail is kilobytes, and a 300 mb "audio/mpeg" is not a voicemail.
   it stays a row with a byte count and is not written.
4. **the player refuses the rest.** `open voicemail --play N` resolves the path and refuses anything that
   is not inside the voicemail folder, or that is not an audio suffix, or that is not a file. a crafted
   inbox row, a symlink, or a typo cannot turn `--play` into "play /etc/shadow" or into launching a
   `.sh`.

## what is still a real risk, said plainly

- **the text is a stranger's.** a transcript, a subject, a body: all of it is untrusted input, and any of
  it can try to instruct the agent reading it. this package does not execute instructions found in
  messages, and the honest guard is that the agent's tools are the agent's, not the message's.
- **the audio is a stranger's.** playing it is safe; believing it is a voice you know is not.
- **the inbox file is writable.** whoever can edit the jsonl can write any path into a row, which is
  exactly why the player checks the folder rather than trusting the row.
- **a caller can still reach a human's phone.** none of this is a defence against being called at all, and
  it was never meant to be.
