# Account sign-ups: the texts to paste (Day 1)

Everything here is ready to copy into the sign-up and application forms. Fill in the `<...>` parts yourself
(your name, email, address); nothing personal is written here. The store listings themselves (screenshots,
the full Store page, the winget/Chocolatey/Scoop manifests) come on Day 9. The description below is Red v1 as planned; Day 9 checks
every claim against what actually ships before anything is public.

**Do this first: make the GitHub repo public.** SignPath Foundation signs only public open-source projects,
SourceForge hosts only open-source projects, and GitHub Pages (the website) is free only for public repos.
Checked on 2026-11-14: a search of all 351 commits for GitHub, Google, OpenAI, Slack and Kaggle tokens and
private keys found nothing, and `.env`, the Google token and the Kaggle key live outside the repo (`.gitignore`
blocks them too). Making it public also publishes the whole history, including plan.md and docs/plan-history.md.
GitHub: Settings → General → Danger Zone → Change visibility → Public.

## The texts every form reuses

| Field | Text |
|---|---|
| Name | Red |
| Longer name, where "Red" is taken | Red: desktop companion |
| ID / URL slug (where one is needed) | `red-companion` |
| One line (≤ 80 characters) | A local AI companion for Windows that talks, remembers you and does the work. |
| Short (≤ 160 characters) | Red lives on the edge of your screen: say "Hey Red" and it writes code, does sums, finds files, sets reminders and drafts mail. All on your PC, no cloud. |
| Licence | MIT |
| Platform | Windows 10 and 11, 64-bit |
| Language | Python 3.11 (shipped inside the installer) |
| Repository | https://github.com/AryanLanke/Red |
| Website (once Pages is on) | https://aryanlanke.github.io/Red/ |
| Downloads | https://github.com/AryanLanke/Red/releases |
| Category words | desktop companion, voice assistant, productivity, accessibility (dictation), offline AI |
| First release | v1.0.0, planned for 2026-11-24 |

**Description (about 150 words), for every "Description" box:**

> Red is a companion that lives on the edge of your Windows screen. Say "Hey Red", or just its name once it's
> out, and ask for what you need: write or fix a piece of code, do a sum, find a file, open an app, set a
> reminder, draft an email. Red says plainly what it did and where the result is.
>
> Everything runs on your PC. Speech recognition (Whisper), the voice and the language model (Qwen, through
> Ollama) are local, and Red never sends your voice or your screen to a cloud service. It remembers what you
> tell it in plain files you can read and delete.
>
> Three companions, Red, Remy and Asha, each with their own voice, personality and memory of your chats. They
> peek from a corner, hang from the top of the screen and react when you pick them up. A dictation mode types
> what you say into any app.
>
> Free and open source (MIT). Works best with an NVIDIA GPU with 4 GB or more; runs on any 64-bit Windows PC
> with 8 GB of RAM.

**Requirements:**

| Tier | PC | First word after you stop talking |
|---|---|---|
| Lite | no GPU, 8 GB RAM | about 2.5 s |
| Standard | NVIDIA GPU with 4 GB (RTX 3050 class) | about 1 s |
| Plus | NVIDIA GPU with 6 GB or more | about 1 s, livelier voice |

Disk: about 150 MB for the installer, then 3.5 to 6 GB of models downloaded on first run (checked against
their SHA-256).

---

## 1. SignPath Foundation (free code signing)

Where: https://signpath.org/apply (the form may change; these are the answers it has asked for).
Why: a signed `Red-Setup.exe` gets past Smart App Control and SmartScreen. Approval takes days to weeks, so
apply today; until then the website shows the "More info → Run anyway" steps and the SHA-256.

| Question | Answer |
|---|---|
| Project name | Red |
| Repository URL | https://github.com/AryanLanke/Red |
| Project homepage | https://aryanlanke.github.io/Red/ (or the repository until Pages is on) |
| Licence | MIT (OSI-approved). No dual licensing, no paid edition |
| Description | the one line above, then the 150-word description |
| What will be signed | `Red-Setup.exe`, the Inno Setup installer, built from the public sources only |
| Build system | GitHub Actions on `windows-latest` (`.github/workflows/installer.yml`). The workflow already builds the installer and uploads it as an artifact, which is how SignPath's GitHub integration picks it up |
| Third-party code in the installer | The embeddable CPython 3.11 from python.org (PSF licence, already signed by the PSF) and open-source Python wheels from PyPI, every one pinned with a SHA-256 (`installer/requirements-lock.txt`). No closed-source parts. Models are downloaded at first run, not shipped |
| Does it download or run other code? | It downloads Ollama and the language and voice models on first run, each pinned to a version and a SHA-256 and refused if the hash differs. It never runs text a model wrote as a command |
| Team / roles | Author, reviewer and approver: `<your name>` (GitHub: AryanLanke). One-person project for now |
| Released before? | First public release v1.0.0 is planned for 2026-11-24. If the form requires an existing release, apply again right after Day 10 and keep this text |
| Contact | `<your email>` |

They also ask the project to publish a **code signing policy**. This text goes on the website (track B adds
it to `site/` on Day 9) and in the README:

> **Code signing policy.** Free code signing provided by [SignPath.io](https://signpath.io), certificate by
> [SignPath Foundation](https://signpath.org). Only `Red-Setup.exe` built by this repository's GitHub Actions
> workflow from a tagged commit is signed. Committer and approver: Aryan Lanke. Red sends nothing about you
> anywhere; see the privacy section for what stays on your PC.

They require two-factor sign-in for both GitHub and SignPath: turn on GitHub 2FA if it isn't on.

## 2. SourceForge (download mirror)

Where: https://sourceforge.net/user/registration, then **Create a Project**.

| Field | Answer |
|---|---|
| Project name | Red: desktop companion |
| URL | `red-companion` (sourceforge.net/projects/red-companion) |
| Summary | the one line above |
| Description | the 150-word description |
| Licence | MIT License |
| Operating system | Windows |
| Programming language | Python |
| Intended audience | End Users/Desktop |
| User interface | Win32 (MS Windows) |
| Categories | Desktop Environment; Speech; Assistive Technology |
| Website | https://aryanlanke.github.io/Red/ |
| Code | "External": https://github.com/AryanLanke/Red (don't create a second repository) |

After v1 (Day 10): **Files → Add File → Red-Setup.exe**, the same file and SHA-256 as on GitHub; mark it as
the default download for Windows. SourceForge's "Import from GitHub" can mirror later releases.

## 3. itch.io (indie store page)

Where: https://itch.io/register, then **Dashboard → Create new project**. Keep it a **Draft** until Day 10.

| Field | Answer |
|---|---|
| Title | Red: desktop companion |
| Project URL | `red-companion` |
| Short description or tagline | Three AI companions that live on your screen and get things done. Local, free, open source. |
| Classification | Tools |
| Kind of project | Downloadable |
| Release status | In development (switch to Released on Day 10) |
| Pricing | No payments (or "$0 or donate", if you'd like tips) |
| Uploads | Day 10: `Red-Setup.exe`, ticked as **Windows** |
| Description | the 150-word description, then the requirements table |
| Genre | (none: it's a tool) |
| Tags | desktop-companion, virtual-pet, voice-assistant, ai, offline, open-source, productivity, dictation, windows |
| AI generation disclosure | Yes: Red uses a local language model and text-to-speech at run time, and the code was written with AI assistance. (Your call how much to say; the companion art's licences are checked on Day 9 before any page goes live) |
| Community | Comments |
| Visibility | Draft |

## 4. Microsoft Partner Center (Microsoft Store)

Where: https://storedeveloper.microsoft.com (it leads to Partner Center). Choose **Individual**. Microsoft
made registration free for individual developers; **check that the page says free before you enter a card**,
and stop if it asks for a fee.

| Field | Answer |
|---|---|
| Account type | Individual |
| Publisher display name | `<your name>`, or "Red Companion" (it's shown on the Store page and must be unique) |
| Contact details | `<your name, email, address, phone>` (Microsoft verifies them with an ID check) |

Once the account is open: **Apps and games → New product → MSIX or PWA app → Reserve a name**. Try in order:
"Red: desktop companion", "Red Companion", "Red AI Companion". Reserving holds the name for 3 months. The
listing (description, screenshots, privacy policy URL, age rating) is Day 9. The MSIX package is signed by
Microsoft on submission.

## 5. Chocolatey (community package manager)

Where: https://community.chocolatey.org/account/Register. Only the account today; the package goes up on Day 9
or after v1 (it's moderated and on the cut line).

| Field | Answer |
|---|---|
| Username | `aryanlanke` (or your usual handle) |
| Email | `<your email>` |

For the package later (`red-companion.nuspec`, written on Day 9):

| nuspec field | Value |
|---|---|
| id | `red-companion` |
| title | Red: desktop companion |
| authors | Aryan Lanke |
| projectUrl | https://github.com/AryanLanke/Red |
| licenseUrl | https://github.com/AryanLanke/Red/blob/main/LICENSE |
| tags | `desktop-companion voice-assistant ai offline foss` |
| summary | the one line above |
| description | the 150-word description |

After signing up, **Account → API key** gives a key for `choco push`. Keep it in `D:\RED\config\secrets\chocolatey.txt`,
never in the repo.

---

## Checklist

- [ ] GitHub repo public (after the secret check), 2FA on
- [ ] SignPath Foundation application sent
- [ ] SourceForge account and the `red-companion` project created
- [ ] itch.io account and a draft `red-companion` page
- [ ] Partner Center individual account (free) and a reserved Store name
- [ ] Chocolatey account
