# Repository working rules

## Installer publication is part of every push

Any source change pushed to `master` is incomplete until the Distribution
workflow succeeds. That workflow must build and test both platform packages,
replace the stable `beta` release assets, and commit the same rolling installers
under `installers/`.

Do not remove, bypass, or defer installer publication to make a source push
pass. If packaging fails, fix the packaging failure or explicitly report the
blocker. Do not manually edit generated files under `installers/`; change the
source or packaging workflow and let CI regenerate them.

The public download URLs documented in `README.md` are compatibility surfaces.
If a URL must change, call it out explicitly in the push or issue closeout so
the project website can be updated.
