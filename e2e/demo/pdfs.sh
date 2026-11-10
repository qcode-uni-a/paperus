#!/usr/bin/env bash
# Typesets the demo library's own documents (*.tex here) into $1: with
# pdflatex where TeX Live has LaTeX (CI installs it), else in an Ubuntu
# container with the same packages.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
PACKAGES="texlive-latex-base texlive-latex-recommended texlive-fonts-recommended texlive-pictures lmodern"
build='for tex in "$SRC"/*.tex; do
  for run in 1 2; do pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$OUT" "$tex" >/dev/null; done
done'
if kpsewhich latex.ltx >/dev/null 2>&1 && kpsewhich lmodern.sty >/dev/null 2>&1; then
  SRC=$HERE OUT=$OUT bash -c "$build"
else
  docker run --rm -e SRC=/src -e OUT=/out -v "$HERE":/src:ro -v "$OUT":/out ubuntu:24.04 bash -c \
    "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends $PACKAGES >/dev/null && $build && chown -R $(id -u):$(id -g) /out"
fi
rm -f "$OUT"/*.aux "$OUT"/*.log "$OUT"/*.out
ls "$OUT"/*.pdf
