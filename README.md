<p align="center">
  <img src="assets/banner.svg" alt="Cabela's 4x4 Revival — community patches and field notes" width="100%">
</p>

<p align="center">
  <img alt="Community patch 1.2.1" src="https://img.shields.io/badge/community_patch-1.2.1-D9773E?style=flat-square&amp;labelColor=24332A">
  <img alt="Windows" src="https://img.shields.io/badge/platform-Windows-9CAE8C?style=flat-square&amp;labelColor=24332A">
  <img alt="Python 3.9 or newer" src="https://img.shields.io/badge/Python-3.9%2B-9CAE8C?style=flat-square&amp;labelColor=24332A">
  <img alt="MIT license for project code" src="https://img.shields.io/badge/project_code-MIT-E4DCC8?style=flat-square&amp;labelColor=24332A">
</p>

<p align="center">
  <strong>Keep the expedition going.</strong><br>
  Small, documented fixes for <em>Cabela's 4x4 Off-Road Adventure</em>.
</p>

---

## The first repair

**Community patch 1.2.1 fixes an original depth-buffer boundary error and preserves your installed game's content.** The defect exists in official 1.2 and the supported compatible 1.2 variant. A visual effect projected onto the first row beyond the bottom of the screen could make the game read outside its depth buffer and crash. The same mistake exists at the right edge.

The fix changes two conditional-branch bytes. Interior screen coordinates keep their existing behavior; out-of-screen coordinates take the game's existing “do not draw this effect” path.

| Field report | Result |
|---|---|
| Captured crash | Pixel row `1800` on a `2880 × 1800` screen; valid rows end at `1799` |
| Root cause | Original bounds checks allowed coordinates equal to width or height |
| Fix | Reject equality at both edges before accessing the depth buffer |
| Offline validation | Actual x86 routine replay: [**61 case pairs, 177 checks**](docs/verification/v1.2.1-replay.json) |
| Build preservation | [**16 isolated-copy checks**](docs/verification/v1.2.1-build-selection.json) across both supported executable builds |
| Gameplay validation | **Pending**; the game and its graphics driver were not launched for verification |

Read the [forensic report](docs/forensics/depth-buffer-bounds.md), [fix specification](fixes/001-depth-buffer-bounds/README.md), and [known issues](docs/known-issues.md).

## Install

You need your own copy of the game, one of the **supported executables below**, and **Python 3.9 or newer** on Windows. Close the game before applying or rolling back a patch. The patcher interface and documentation are in English.

Download and extract the [latest release](../../releases/latest), open a terminal in the extracted project folder, and run:

```powershell
python src/patcher.py apply --game-dir "C:\Games\Cabela4x4"
python src/patcher.py verify --game-dir "C:\Games\Cabela4x4"
```

Replace the example folder with the folder containing `4x4 Adventure.exe`. The patcher automatically recognizes its exact size and SHA-256, reports the selected build identity, and retains that executable as the rollback backup. It changes the two bounds-check bytes and PE checksum in your existing executable, preserving its other content and the installation's resources. An unknown executable needs a separate reviewed manifest.

To restore the pre-patch executable:

```powershell
python src/patcher.py rollback --game-dir "C:\Games\Cabela4x4"
```

### Supported builds

| Executable | Build | Language | Original SHA-256 |
|---|---|---|---|
| `4x4 Adventure.exe` | Official 1.2 | English (`en`) | `e9c5d3932dc87accd8a1d94a264de1badbe7edac73afaf1fa78181a30c624d1c` |
| `4x4 Adventure.exe` | Compatible 1.2 variant (`compatible-1-2-variant`) | Unspecified (`und`) | `ab517697d459912a924f8502b1be5b38d69c3bd4e8a3011689c5eca16077f765` |

The version number or descriptive metadata alone is insufficient: different releases or other modifications can produce different binaries. See the machine-readable [manifest](fixes/001-depth-buffer-bounds/manifest.json) for original and patched identities. Already-patched builds are recognized too. Rollback requires the original backup for that exact build; a backup from another build is refused.

The compatible variant is identified by its exact hash; it is not described as an official release. This repository and its releases contain identification metadata and patch instructions, without game assets or executables.

### Original installer support

The [native installer sources](tools/native-installshield/README.md) support a
private rebuild of the original InstallShield wizard that patches the selected
folder's executable and preserves the selected build's existing content. Its worker and real
x86 interface passed 165 isolated-copy checks. Full wizard completion remains
unverified because a silent test without elevation stopped at legacy Error 432
before the patch script. The original installer components are not published.

## Inside the project

```text
cabelas-4x4-revival/
├── src/
│   └── patcher.py                 Apply, verify, and roll back reviewed fixes
├── fixes/
│   └── 001-depth-buffer-bounds/
│       ├── manifest.json          Supported builds, byte edits, and hashes
│       └── README.md              Fix scope and installation details
├── docs/
│   ├── forensics/
│   │   └── depth-buffer-bounds.md  Evidence and causal analysis
│   ├── verification/
│   │   ├── v1.2.1-replay.json      Machine-code replay results
│   │   └── v1.2.1-build-selection.json  Supported-build lifecycle results
│   └── known-issues.md            Remaining renderer questions
├── tests/                         Patcher and boundary regression checks
├── tools/
│   └── native-installshield/       Patch worker, native bridge and private script authoring
├── assets/
│   └── banner.svg                 Original project artwork
├── .github/                       Automated project checks
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
└── pyproject.toml
```

## What “Revival” means here

Each fix starts with a concrete failure, identifies the responsible layer, and records its smallest defensible correction. A modern graphics wrapper may make an old defect easier to observe; that does not automatically make the wrapper responsible, or prove the game could never have failed on its original operating systems.

This release addresses the demonstrated boundary error. Further compatibility work is tracked in [known issues](docs/known-issues.md). The goal is a useful, reviewable preservation project with honest validation records.

## Help improve it

Reports with an exact executable hash, exception address, graphics-wrapper version, and reproduction steps are especially useful. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting evidence or a patch.

Project code and original project artwork are available under the [MIT license](LICENSE). The game, official executable, game assets, and third-party wrappers retain their respective rights. Releases contain the patch tools and documentation; obtain the game separately.

*An independent community project. Community version 1.2.1 builds on official game version 1.2.*
