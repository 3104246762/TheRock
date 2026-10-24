# Building ROCm on Windows via GitHub Actions (single GPU family)

This guide explains how to use the
[`build_windows_single_family.yml`](../../.github/workflows/build_windows_single_family.yml)
workflow to build a ROCm / HIP SDK distribution for **one AMD GPU family** on Windows, and how to
install and verify the result on the build machine.

It complements the general source-build instructions in [README.md](../../README.md) and
[windows_support.md](windows_support.md). It exists because the upstream
`multi_arch_build_windows*.yml` release pipelines run on AMD's internal self-hosted runners and pass
artifacts through internal S3 buckets; neither is available outside AMD, and GitHub-hosted runners
cannot hold a full ROCm source build (see [Why a self-hosted runner](#why-a-self-hosted-runner)).

The reference configuration used while writing this guide:

| Item            | Value                                              |
| --------------- | -------------------------------------------------- |
| OS              | Windows 11 (x64)                                   |
| CPU             | AMD Ryzen 7 5700X (8 cores), 32 GB RAM             |
| GPU             | Radeon RX Vega (Vega 10, **gfx900**, 56 CUs, 8 GB) |
| Driver          | AMD Software: Adrenalin Edition (`31.0.21924.61`)  |
| TheRock version | `10.2.0` (from `version.json`)                     |

## Choosing the build target

Pick the AMDGPU family that matches your GPU. The list of valid families and targets lives in
[`cmake/therock_amdgpu_targets.cmake`](../../cmake/therock_amdgpu_targets.cmake); the workflow
validates your choice against it before building anything.

| GPU                                              | LLVM target | Family to use                 |
| ------------------------------------------------ | ----------- | ----------------------------- |
| Radeon RX Vega / Instinct MI25 (Vega 10, GCN5.0) | `gfx900`    | `gfx900` (or `gfx900-dgpu`)   |
| Radeon VII / MI50 (GCN5.1)                       | `gfx906`    | `gfx906` (or `gfx906-dgpu`)   |
| RX 5700 XT (RDNA1)                               | `gfx1010`   | `gfx1010`, `gfx101X-all`, ... |
| RX 6900/6800 XT (RDNA2)                          | `gfx1030`   | `gfx1030`, `gfx103X-all`, ... |
| RX 7900 XTX (RDNA3)                              | `gfx1100`   | `gfx1100`, `gfx110X-all`, ... |
| RX 9070 XT (RDNA4)                               | `gfx1201`   | `gfx1201`, `gfx120X-all`, ... |

> [!WARNING] **`gfx900` (Vega 10) on Windows is a "builds but unverified" target.**
> [SUPPORTED_GPUS.md](../../SUPPORTED_GPUS.md) marks it *Build Passing* (CI publishes artifacts) but
> **not** *Sanity Tested* and **not** *Release Ready*, and AMD's official Windows HIP SDK support
> matrix does not list Vega at all. On the reference machine, the driver-bundled HIP runtime (used
> by ROCm 5.7) detects the GPU, but the ROCm 6.2 runtime reports *"no ROCm-capable device is
> detected"* and the ROCm 7.2 runtime crashes. Expect the build to succeed; whether the result runs
> on a Vega GPU is an open question that only the `gpu-validate` job can answer. Also note that some
> sub-projects are excluded for `gfx900` (hipBLASLt, hipSPARSELt, hipTensor, rocWMMA,
> composable_kernel, rocprofiler-compute), so the built ROCm is not feature-complete.

## Why a self-hosted runner

A full ROCm source build needs roughly **150-200 GB** of disk space (see the warning in
[README.md](../../README.md)) and several hours on 8 CPU cores. GitHub-hosted Windows runners
provide **~14 GB of SSD** (4 vCPU / 16 GB RAM on public repositories, 2 vCPU / 8 GB on private
ones), so they cannot host this build. That is why the upstream Windows release workflows use AMD's
own large self-hosted runners plus internal artifact storage.

This workflow therefore defaults to a **self-hosted Windows runner** (which can be the very machine
that will use the ROCm build - the artifacts never have to leave it). If you have access to GitHub
larger runners with enough disk, set the `runner_labels` input to those labels instead; nothing else
changes.

## One-time setup

### 1. Register a self-hosted runner

On the machine that will build (and use) ROCm:

1. Open your fork on GitHub -> **Settings -> Actions -> Runners -> New self-hosted runner**.
1. Download and configure the Windows runner, e.g.:
   ```powershell
   # In an empty directory on a drive with room for the runner itself:
   .\config.cmd --url https://github.com/<your-user>/TheRock --token <token> --labels rocm-build --runasservice
   ```
   Add the label **`rocm-build`** (the workflow's default `runner_labels` input is
   `["self-hosted", "Windows", "X64", "rocm-build"]`; adjust if you use different labels).
1. Start the runner service (`.\run.cmd` interactively for the first test).
1. Keep it **persistent** (do not use `--ephemeral`): the `gpu-validate` job reads the build output
   from the previous job on the same machine.

Recommendations for the runner machine:

- Put the runner's **work directory** on a drive with at least ~25 GB free (checkout + submodule
  sources + Python venv).
- The `build_dir` input (default `D:/therock-build`) must have roughly **150-200 GB free**. On the
  reference machine `D:` has ~203 GB free, while `C:` has only ~52 GB, hence the default.
- Do not run the runner as an ephemeral container.

### 2. Toolchain

The workflow's `preflight` job installs what is missing (Visual Studio 2022 Build Tools with MSVC
19.43+/17.13+, CMake, Ninja, Strawberry Perl for gfortran/patch, Git for Windows for bash, Python
3.12 when no runnable Python 3.11+ is on PATH) via `winget`. You can also install them up front
yourself - see [windows_support.md](windows_support.md#install-tools) for the full list. Useful
one-time commands:

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --source winget --override "--add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.VC.CMake.Project --add Microsoft.VisualStudio.Component.VC.ATL --add Microsoft.VisualStudio.Component.Windows11SDK.26100"
winget install cmake ninja-build.ninja strawberryperl
git config --global core.symlinks true
git config --global core.longpaths true
```

**Python**: the build job uses the runner's own `python` (any 3.11+; the build tools import
`tomllib`, which is standard library since 3.11) instead of `actions/setup-python`. That action
downloads its version manifest from `raw.githubusercontent.com`, which is not reachable from
every network (in mainland China the domain is DNS-poisoned, producing
`unable to verify the first certificate` / `Failed to fetch the Python versions manifest`).
Using the runner's Python keeps the build free of that dependency. `preflight` verifies a
runnable Python exists and installs Python 3.12 via winget if not; note that a winget install
mid-run needs a runner restart before the `build` job can see the new PATH.

**Runner PATH vs. tools on disk**: a self-hosted runner keeps the PATH of the process that
started it, so tools installed *after* the runner was started are invisible to `Get-Command`
even though they are on disk (this is the usual reason a tool shows up as "missing" while
`winget` simultaneously reports "Found an existing package already installed"). The workflow
handles this: `preflight` probes the well-known install locations (`C:\Program Files\CMake\bin`,
the Visual Studio bundled CMake, `C:\Strawberry\c\bin`, `C:\Program Files\Git\bin`, the winget
links directory, ...) and exposes what it finds through `GITHUB_PATH`, and the `build` /
`gpu-validate` jobs repeat that probe for their own processes. A non-zero `winget` exit code is
therefore never fatal by itself - the tool is verified by actually running it afterwards.
Restarting the runner service after installing tools is still the cleanest long-term fix.

**GitHub clone acceleration (`gh-proxy.org`)**: a build clones TheRock itself plus 12 submodules from
`github.com` (the `amd-llvm` submodule alone is several GB), and direct clones often stall or fail
mid-transfer from restricted networks. The `build` job therefore probes direct access *before*
checking out - an HTTPS request against the git smart-HTTP discovery endpoint
(`<repo>/info/refs?service=git-upload-pack`) plus a real `git ls-remote`, because a proxy that
serves browsers does not necessarily serve git. When either probe fails - or when you set the
`force_github_proxy` input - it rewrites all `github.com` and `raw.githubusercontent.com` URLs
through the `https://gh-proxy.org/` mirror:

```bash
git config --global url."https://gh-proxy.org/https://github.com/".insteadOf "https://github.com/"
git config --global url."https://gh-proxy.org/https://raw.githubusercontent.com/".insteadOf "https://raw.githubusercontent.com/"
```

The config is `--global`, so it also covers the submodule fetches in `Fetch sources`; that step
additionally retries once through the mirror if it fails. The mirror is only a warning, never a hard
failure - if it does not answer either, the workflow keeps the rewrite and lets the clone try
anyway. To undo the rewrite on the machine:

```bash
git config --global --unset 'url.https://gh-proxy.org/https://github.com/.insteadOf'
git config --global --unset 'url.https://gh-proxy.org/https://raw.githubusercontent.com/.insteadOf'
```

Note that the mirror proxies git's smart HTTP protocol, so `git clone`, `git fetch` and submodule
updates all work through it. Private repositories would need credentials for the mirrored host, which
the mirror cannot forward - irrelevant here, as TheRock and all submodules are public.

You can sanity-check the machine at any time with the repository's own validator:

```powershell
.\build_tools\validate_windows_install.ps1
```

Notes from running it on the reference machine: RAM (32 GB) and long-path support are fine; `C:`
free space (52 GB) is only enough for the runner workspace, which is why the build directory
defaults to `D:`. It also warns about the pre-existing ROCm installs
(`C:\Program Files\AMD\ROCm\5.7`, `6.2`, `7.2` and a `HIP_PATH` environment variable pointing at
`6.2`) - see [Known conflicts](#known-conflicts).

### 3. Enable the workflow

Workflows from the default branch run immediately; for a fork, push the branch containing
`build_windows_single_family.yml` (the file only becomes active once it is on the default branch or
the run is triggered from that branch):

```bash
git add .github/workflows/build_windows_single_family.yml build_tools/github_actions/validate_amdgpu_selection.py docs/development/github_actions_windows_build.md
git commit -m "ci: add Windows single-family ROCm build workflow (default gfx900)"
git push
```

## Triggering a build

The workflow is **manual only** (`workflow_dispatch`): a full build takes hours and should not run
on every push.

1. Go to the **Actions** tab of your fork.
1. Select **"Build ROCm (Windows, single GPU family)"**.
1. Click **Run workflow**, choose the branch, and set the inputs:

| Input                | Default                                           | Notes                                                                                                                     |
| -------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `amdgpu_family`      | `gfx900`                                          | Must exist in `cmake/therock_amdgpu_targets.cmake`.                                                                       |
| `runner_labels`      | `["self-hosted", "Windows", "X64", "rocm-build"]` | JSON array; point at larger runners if you have them.                                                                     |
| `build_dir`          | `D:/therock-build`                                | Needs ~150-200 GB free.                                                                                                   |
| `ref`                | *(trigger ref)*                                   | Branch/tag/SHA to build.                                                                                                  |
| `release_type`       | `dev`                                             | Version stamping: `dev`, `nightly`, `ci`, ...                                                                             |
| `enable_media_libs`  | `false`                                           | amd-mesa VA-API + rocDecode; adds time/disk and needs winflexbison3.                                                      |
| `enable_ml_libs`     | `true`                                            | MIOpen etc.; the largest component. Turn off to cut build time/disk.                                                      |
| `use_ccache`         | `true`                                            | Compiler cache; disable if you hit `lld-link: error: duplicate symbol`.                                                   |
| `run_gpu_validation` | `true`                                            | Runs `gpu-validate` on runners with an AMD GPU.                                                                           |
| `upload_artifacts`   | `false`                                           | Upload the multi-GB tarball as a workflow artifact (see storage limits below).                                            |
| `force_github_proxy` | `false`                                           | Always clone GitHub repos through the `gh-proxy.org` mirror, even if direct access works (see [Toolchain](#2-toolchain)). |

The workflow runs five jobs:

1. **Validate build target** (hosted Ubuntu, seconds): validates the GPU family and reports which
   sub-projects are excluded for it.
1. **Preflight checks** (your runner): OS/RAM/disk checks, AMD GPU and driver detection, git config,
   and installation of missing tools.
1. **Build** (your runner, up to 6 h): `fetch_sources.py`, CMake configure with
   `--preset=windows-release -DTHEROCK_AMDGPU_FAMILIES=<family>`, then
   `cmake --build build --target therock-artifacts therock-dist`, output verification, and
   packaging. **Compile-only.**
1. **GPU runtime verification** (only if the runner has an AMD GPU): runs the built `hipInfo.exe`
   and compiles/runs a HIP vector-add kernel with the built `amdclang++`. This is the only real GPU
   verification.
1. **Result summary** (hosted Ubuntu): a table that separates "compiled" from "verified on GPU".

## Getting the build artifacts

### On the build machine (default, recommended)

Because the runner is your own machine, the results are already local:

| Output             | Path                                                                   |
| ------------------ | ---------------------------------------------------------------------- |
| Unpacked ROCm tree | `<build_dir>/dist/rocm/` (ready to use as `ROCM_HOME`)                 |
| Dist tarball       | `<build_dir>/therock-dist-windows-<family>-<version>.tar.gz`           |
| Build metadata     | `<build_dir>/BUILD_INFO.txt` (also a workflow artifact `build-info-*`) |
| Stage artifacts    | `<build_dir>/artifacts/*.tar.xz`                                       |

The tarball follows the published naming convention
`therock-dist-{platform}-{family}-{version}.tar.gz` (see [RELEASES.md](../../RELEASES.md)); its root
contains `bin/`, `lib/`, `include/`, `share/`, `.kpack/` (when kpack splitting is enabled), i.e. it
is a raw install prefix with no install scripts.

### As a workflow artifact (optional)

Set `upload_artifacts=true` to also upload the tarball to the run's artifacts (downloadable from the
run page). Be aware of GitHub's artifact storage limits: **GitHub Free includes only 500 MB** of
artifact storage (Pro 1 GB, Team 2 GB, Enterprise 50 GB), and a full ROCm dist tarball is multiple
GB. The upload will fail on plans without enough headroom. Alternatives for moving the tarball
elsewhere: copy it from the build machine, upload it to a GitHub Release (subject to per-file
limits), or use external storage. Small artifacts (`build-info-*`, and `build-diagnostics-*` on
failure) are always uploaded.

### Matching requirements

The artifacts are **not** portable across machines in general. They match:

- **OS/arch**: Windows x64 only.
- **GPU architecture**: the selected `amdgpu_family` only (e.g. a `gfx900` build contains device
  code for Vega 10; it will not run on RDNA GPUs).
- **Driver**: a recent AMD Adrenalin driver that supports your GPU (the HIP runtime on Windows talks
  to the AMD kernel driver).
- The ROCm version string (e.g. `10.2.0.dev0+<git-sha>`) identifies the exact source commit.

## Installing and verifying on the machine

```powershell
# 1. Extract the tarball anywhere; that directory becomes ROCM_HOME.
mkdir C:\rocm-gfx900
tar -xf D:\therock-build\therock-dist-windows-gfx900-10.2.0.dev0+<sha>.tar.gz -C C:\rocm-gfx900

# 2. Use it (per-session):
$env:ROCM_HOME = "C:\rocm-gfx900"
$env:HIP_PATH  = "C:\rocm-gfx900"
$env:PATH      = "C:\rocm-gfx900\bin;$env:PATH"

# 3. Verify the GPU is seen by the built runtime:
C:\rocm-gfx900\bin\hipInfo.exe
```

Expect a line like `gcnArchName: gfx900:xnack-` in the `hipInfo` output. If it reports *"no
ROCm-capable device is detected"* or crashes, the build compiled but the runtime does not work with
your GPU/driver - see the support status above.

To compile a HIP program:

```powershell
# amdclang++ is the recommended compiler (see docs/development/hipcc_migration.md)
C:\rocm-gfx900\bin\amdclang++.exe -x hip vecadd.cpp -o vecadd.exe --offload-arch=gfx900 --hip-path=C:\rocm-gfx900 -O2
```

> [!TIP] Windows DLL search order matters: the directory of the executable is searched before
> `System32`, but `PATH` is searched **after** `System32`. Run built executables from inside `bin\`
> (or next to the runtime DLLs); do not rely on `PATH` overriding a driver-installed `amdhip64.dll`
> in `System32`. See [windows_support.md](windows_support.md#dll-search-and-runtime-loading).

## Known conflicts

- **Pre-existing ROCm / HIP SDK installs**: the reference machine has ROCm 5.7/6.2/7.2 under
  `C:\Program Files\AMD\ROCm` and a `HIP_PATH` environment variable. These are known to break
  TheRock builds (ROCm/TheRock#651). The workflow unsets `HIP_PATH`/`ROCM_PATH`/`HIP_CLANG_PATH`
  during configure and build, but if you still see HIP-related configure errors, uninstall the
  pre-existing HIP SDK and re-run. Keep at least one working install if you need it for other
  software - it does not interfere as long as `PATH` order prefers the built distribution when you
  test.
- **Non-UTF-8 code page**: on Chinese Windows the active code page is 936; run `chcp 65001` before
  building interactively to avoid path encoding issues.
- **Symlinks**: enable Developer Mode or grant "Create symbolic links" if the build reports symlink
  errors.

## Common failures

| Symptom                                                                                                   | Cause / fix                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `validate-config` fails                                                                                   | The `amdgpu_family` input is not a known family/target; the job prints the valid list.                                                                                                                                                                                                                                                                                                                                                                   |
| Preflight fails on disk                                                                                   | `build_dir` drive has < 100 GB free (hard fail) or < 200 GB (warning). Point `build_dir` at a bigger drive; the runner workspace needs ~25 GB on its own drive.                                                                                                                                                                                                                                                                                          |
| Preflight fails: "Tools still not usable after installation"                                              | A tool is genuinely missing (or broken) after winget ran. The message lists which one; install it manually (CMake 3.25+, Ninja, Strawberry Perl for gfortran/patch, Git for Windows for bash, Python 3.11+, VS 2022 Build Tools 17.13+), then restart the runner service so it picks up the updated machine PATH.                                                                                                                                        |
| `winget failed to install ...` / `No available upgrade found` / `No newer package versions are available` | winget exits non-zero when the package is already installed and cannot be upgraded (or a source is unreachable). This is no longer fatal: the workflow verifies the tool on disk instead, so the step only fails when the tool is really missing. If the tool *is* installed but not on the runner PATH, the workflow exposes it via `GITHUB_PATH` (see "Runner PATH vs. tools on disk" above); restarting the runner service also fixes it permanently. |
| `Failed to fetch the Python versions manifest` / `unable to verify the first certificate`                 | `actions/setup-python` fails when the runner cannot reach `raw.githubusercontent.com` (the domain is DNS-poisoned on some networks, e.g. mainland China). This workflow deliberately avoids that action and uses the runner's own Python 3.11+ instead, so this error should no longer occur.                                                                                                                                                            |
| Clone from `github.com` fails or stalls mid-transfer (`Checkout` / `Fetch sources`)                       | Direct GitHub access is blocked or throttled. The `Configure GitHub proxy acceleration` step probes it first and rewrites GitHub URLs through `gh-proxy.org` only when the probe fails; `Fetch sources` also retries once through the mirror. To always use the mirror, set the `force_github_proxy` input when triggering the workflow.                                                                                                                 |
| `gh-proxy.org` unreachable / rate-limited                                                                 | The mirror is down or throttling. The workflow only warns in that case (it keeps the rewrite and lets the clone try); unset the rewrite on the machine (see "GitHub clone acceleration" above) and re-run, or retry later - once the direct probe succeeds again the mirror is not used.                                                                                                                                                                 |
| `No Visual Studio installation found`                                                                     | Install VS 2022 Build Tools 17.13+ (MSVC 19.43+); older MSVC fails at link time (ROCm/TheRock#5029).                                                                                                                                                                                                                                                                                                                                                     |
| `lld-link: error: duplicate symbol` in rocBLAS/rocSPARSE                                                  | Known ccache issue on Windows; re-run with `use_ccache=false`.                                                                                                                                                                                                                                                                                                                                                                                           |
| `No such file or directory: (long path ...)`                                                              | Long paths not enabled: `git config --global core.longpaths true` and re-run `fetch_sources.py`.                                                                                                                                                                                                                                                                                                                                                         |
| `error: directive requires gfx90a+`                                                                       | A selected target is not supported by some library; the family list in the failure message shows what to change.                                                                                                                                                                                                                                                                                                                                         |
| Build exceeds the 6 h job limit                                                                           | GitHub caps a job at 360 minutes. Re-run: ccache and the persistent runner resume where the build stopped. To reduce scope, set `enable_ml_libs=false` (MIOpen is the largest component) and `enable_media_libs=false`.                                                                                                                                                                                                                                  |
| `gpu-validate` fails with "Built dist not found"                                                          | The runner is ephemeral (`--ephemeral`); files do not persist between jobs. Use a persistent runner or verify manually on the build machine.                                                                                                                                                                                                                                                                                                             |
| `hipInfo` reports no device / crashes                                                                     | The built runtime does not support the GPU/driver combination. For `gfx900` on Windows this is a known open question (see [Choosing the build target](#choosing-the-build-target)). The build itself succeeded.                                                                                                                                                                                                                                          |
| Artifact upload fails (size)                                                                              | Plan artifact storage limit (GitHub Free: 500 MB). Use the local `build_dir` paths instead.                                                                                                                                                                                                                                                                                                                                                              |

## Relationship to the upstream workflows

`build_windows_single_family.yml` is additive: it does not modify `multi_arch_build_windows.yml`,
`multi_arch_build_windows_artifacts.yml`, or any other upstream workflow. It reuses the same
documented build commands, CMake presets (`windows-release`), version computation
(`build_tools/compute_rocm_package_version.py`), source fetching (`build_tools/fetch_sources.py`,
which also performs the in-tree DVC pulls for the CLR interop payload), and artifact naming
conventions (`therock-dist-{platform}-{family}-{version}.tar.gz`). What it deliberately does *not*
use: AMD-internal runner labels, the internal Chocolatey mirror, the S3 artifact buckets, and Quartz
reporting.
