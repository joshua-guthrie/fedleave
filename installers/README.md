# Committed rolling installers

This directory is the repository mirror of the most recent successful
`master` build. GitHub Actions generates these files; do not edit them by hand.

Stable committed-file URLs:

- Windows installer:
  <https://github.com/joshua-guthrie/fedleave/raw/refs/heads/master/installers/FedLeave-Setup-Latest-Windows-x64.exe>
- Linux bootstrap:
  <https://raw.githubusercontent.com/joshua-guthrie/fedleave/master/installers/install.sh>
- Linux archive:
  <https://github.com/joshua-guthrie/fedleave/raw/refs/heads/master/installers/FedLeave-Latest-Linux-x86_64.tar.gz>

The Windows installer and Linux archive are stored with Git LFS because each
exceeds GitHub's 100 MiB regular-Git file limit. The `BUILD.txt` file identifies
the source commit and version used to create the mirrored files.

The release-asset URLs in the main README remain the preferred public download
links. They do not consume the repository owner's Git LFS bandwidth allowance.
