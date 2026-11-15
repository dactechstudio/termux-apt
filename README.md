# Termux ARM64 package repository

Signed APT packages for the Android application `com.dactechstudio.termux`.
This repository contains generated package files and APT metadata. The
application source remains in a separate private repository.

When GitHub Pages is enabled with **Deploy from a branch → main → /(root)**,
the repository URL is `https://dactechstudio.github.io/termux-apt/`.

The repository includes the network utilities `dnsutils` (`dig`, `nslookup`)
and `netcat-openbsd`. Install them in the app with:

```sh
pkg install dnsutils netcat-openbsd
```

Additional Termux packages require custom-prefix builds before they can be
installed from this repository.
