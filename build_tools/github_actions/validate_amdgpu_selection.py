#!/usr/bin/env python3
# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

"""Validates an AMDGPU family/target selection against the repository's target
definitions in cmake/therock_amdgpu_targets.cmake.

Used by the "Build ROCm (Windows, single GPU family)" workflow to fail fast on
typos and to report which sub-projects are excluded for the selected target.

Writes results to $GITHUB_OUTPUT when running under GitHub Actions:
  - valid: "true"/"false"
  - resolved_targets: space-separated list of gfx targets the selection builds
  - offload_arch: first resolved target (for --offload-arch)
  - excluded_projects: comma-separated sub-projects excluded for the selection
"""

import os
import re
import sys

TARGETS_FILE = "cmake/therock_amdgpu_targets.cmake"


def parse_targets(text):
    """Returns {target_name: (product_name, [families], [excluded_projects])}."""
    targets = {}
    pattern = re.compile(
        r"therock_add_amdgpu_target\(\s*(\S+)\s+\"([^\"]*)\"(.*?)\n\)", re.S
    )
    for match in pattern.finditer(text):
        name, product, rest = match.groups()
        families = []
        fam_match = re.search(r"FAMILY\s+([^)\n]*)", rest)
        if fam_match:
            families = fam_match.group(1).split()
        excluded = []
        # Note: the outer capture already consumed the block's closing ")",
        # so the excluded list simply runs to the end of `rest`.
        exc_match = re.search(r"EXCLUDE_TARGET_PROJECTS(.*)", rest, re.S)
        if exc_match:
            excluded = [
                tok
                for tok in exc_match.group(1).split()
                if not tok.startswith("#") and not tok.startswith("http") and tok != ")"
            ]
        targets[name] = (product, families, excluded)
    return targets


def main():
    selection = sys.argv[1].strip()
    with open(TARGETS_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    targets = parse_targets(text)
    if not targets:
        print(f"ERROR: no targets parsed from {TARGETS_FILE}")
        sys.exit(2)

    # Every target is also a family of the same name; named families group
    # multiple targets (e.g. "gfx110X-all").
    family_to_targets = {}
    for name, (_product, families, _excluded) in targets.items():
        family_to_targets.setdefault(name, set()).add(name)
        for fam in families:
            family_to_targets.setdefault(fam, set()).add(name)

    if selection in family_to_targets:
        resolved = sorted(family_to_targets[selection])
        excluded = set()
        for target in resolved:
            excluded.update(targets[target][2])
        products = sorted({targets[t][0] for t in resolved})
        valid = True
    else:
        resolved = []
        excluded = set()
        products = []
        valid = False

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"valid={'true' if valid else 'false'}\n")
            f.write(f"resolved_targets={' '.join(resolved)}\n")
            f.write(f"offload_arch={resolved[0] if resolved else ''}\n")
            f.write(f"excluded_projects={','.join(sorted(excluded))}\n")

    if not valid:
        print(f"ERROR: '{selection}' is not a known AMDGPU family or target.")
        print("Available families/targets:")
        for fam in sorted(family_to_targets):
            members = " ".join(sorted(family_to_targets[fam]))
            print(f"  {fam} -> {members}")
        sys.exit(1)

    print(f"Selection '{selection}' is valid.")
    print(f"  Products : {', '.join(products)}")
    print(f"  Targets  : {' '.join(resolved)}")
    if excluded:
        print(f"  Excluded sub-projects for this target: {', '.join(sorted(excluded))}")
    else:
        print("  Excluded sub-projects: (none)")


if __name__ == "__main__":
    main()
