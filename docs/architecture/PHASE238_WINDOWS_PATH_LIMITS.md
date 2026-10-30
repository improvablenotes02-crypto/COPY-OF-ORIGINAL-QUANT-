# Phase 238 — Windows filename portability limits

The release-candidate verifier now rejects Windows DOS device aliases using
superscript 1/2/3 suffixes (`COM¹` through `COM³`, `LPT¹` through `LPT³`) and
rejects any path component exceeding 255 UTF-16 code units. These checks are
applied to manifest paths independent of the host operating system.

Regression coverage includes all six superscript device spellings, an
oversized component, and a valid nested Unicode path. This is static archive
validation; it is not a substitute for executing extraction on a native
Windows runner. Hosted CI remains unverified until an actual GitHub Actions run
is observed.
