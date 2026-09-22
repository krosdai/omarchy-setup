# Omarchy setup index

This repository recommends independently installable Omarchy plugins. It is no
longer the `krosdai.chinese-input` plugin and must not ship a plugin manifest,
launcher, installer or desktop preset.

## Ownership

- `README.md`: human installation order, optional choices, migration and safety notes.
- `plugins.json`: maintained and external plugin inventory, in recommended order.
- `tests/test_index.py`: portable inventory/documentation consistency checks.
- Feature implementations and regression tests live in sibling repositories under
  `~/repos/krosdai.omarchy-<feature>`; each must work without this index at runtime.

## Constraints

Every listed feature is optional unless a real dependency is documented. Distinguish
local unpublished sources from public Git URLs. Keep external repositories upstream;
verify their actual install method and explain binding conflicts or privileged effects.
Never run an installer or change the user's desktop to test documentation.

Retain migration guidance for existing dictionaries, completion markers, backups,
Lua snippets and time-zone services. Removing a setup launcher is not the same as
undoing the system or user settings it installed.

## Verification

Use `mise run setup` for development dependencies, then run `pnpm test` and
`pnpm run lint`. Preserve the existing linter and formatter configuration.
Plugin manifest validation belongs in the individual plugin repositories, using
clean exports when development directories contain symlinks.

Do not publish, push or install plugins without authorization.
