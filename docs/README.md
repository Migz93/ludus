<!-- shared: structure — keep headings aligned across Migz93 self-hosted apps -->

# Technical Docs

This folder is Ludus's long-term technical reference area.

Use these docs for implementation details, subsystem behaviour, and architecture
notes that stay useful after the branch or issue that introduced them is long
gone. Anything that is only true for one branch or issue belongs in that issue,
not in a file here.

## Where Information Lives

| Kind of information | Where it goes |
|---|---|
| Always true, needed on every task | `AGENTS.md` |
| True only while doing a particular kind of work | the matching `docs/*.md` |
| True only for one branch or issue | that issue or PR |

## Shared Docs

These use the same general structure as the other Migz93 self-hosted projects.
Each carries a `shared:` marker comment on its first line saying whether its
**content** is kept identical or only its **structure**, with app-specific
content underneath.

| Doc | Read it when | Shared |
|---|---|---|
| [architecture.md](architecture.md) | You need the big-picture mental model before touching the code | structure |
| [deployment.md](deployment.md) | Changing installation, systemd, PAM, SELinux, firewalling, or runtime paths | structure |
| [workflow.md](workflow.md) | Opening a PR, releasing, or using CodeRabbit | structure |
| [maintenance.md](maintenance.md) | Changing repair, cleanup, recovery, or removal behaviour | structure |

## Ludus Docs

| Doc | Read it when |
|---|---|
| [shared-libraries.md](shared-libraries.md) | Changing Steam library sharing, mounts, user enrolment, or `ludusctl` |
| [webui.md](webui.md) | Changing the management WebUI, authentication, or LAN exposure |
| [mqtt.md](mqtt.md) | Changing Home Assistant MQTT discovery, status, or commands |
| [status.md](status.md) | Checking the current implementation and remaining validation work |

## Maintenance Rule

When a major feature or long-lived internal behaviour changes, update the
relevant doc in this folder in the same branch/PR. If no existing doc fits, add
a new topic doc here and link it from the table above.

If you change a doc marked `shared: content`, make the same change in sibling
projects. If you change the headings of a doc marked `shared: structure`,
change them in the siblings too — the content underneath is expected to differ.
