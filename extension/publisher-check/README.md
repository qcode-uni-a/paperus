# Checking the extension on publishers' sites

For #41 ("Extension verified on major publisher websites"): one article per
publisher, each tried three ways. About half an hour, on a network or login
with access to these journals (campus, VPN).

## Before

1. The extension installed and connected (`../README.md`), in Firefox and
   in Chrome if both are to be checked.
2. In paperus, Settings → Import: `publishers.bib`. Its papers land in the
   collection "Publisher check", without PDFs.

## For each publisher

1. **Article page**: open the DOI below, click the paperus button. Saved,
   with its PDF? (The paper exists already: the PDF joins it.)
2. **PDF page**: open the article's PDF itself, click the button. Saved
   into the same paper, no second one?
3. **Manage → Missing**: with the PDF deleted from the paper again (or
   for all at once before steps 1–2: "Get all … PDFs with the
   extension"), "Get with the extension" on its row. Fetched? If not,
   what reason does paperus give (a check for robots, no access, no PDF)?

Each failure says why on the page or in the small window; the extension's
log also reaches Administration → Logs (which publisher, what was refused).
A failure to report: the publisher, the browser, the step, that reason, and
the log lines.

| Publisher | Article | Article page | PDF page | Missing |
| --- | --- | --- | --- | --- |
| APS (Physical Review) | [10.1103/RevModPhys.91.045002](https://doi.org/10.1103/RevModPhys.91.045002) | | | |
| Nature | [10.1038/s41586-021-03819-2](https://doi.org/10.1038/s41586-021-03819-2) | | | |
| Springer | [10.1007/s11263-019-01228-7](https://doi.org/10.1007/s11263-019-01228-7) | | | |
| Elsevier (ScienceDirect) | [10.1016/j.jbi.2019.103208](https://doi.org/10.1016/j.jbi.2019.103208) | | | |
| Wiley | [10.1002/qj.3803](https://doi.org/10.1002/qj.3803) | | | |
| IOP | [10.1088/1361-648X/ab51ff](https://doi.org/10.1088/1361-648X/ab51ff) | | | |
| ACS | [10.1021/acs.chemrev.8b00705](https://doi.org/10.1021/acs.chemrev.8b00705) | | | |
| IEEE Xplore | [10.1109/TNNLS.2020.2978386](https://doi.org/10.1109/TNNLS.2020.2978386) | | | |
| AIP | [10.1063/5.0004608](https://doi.org/10.1063/5.0004608) | | | |
| AVS | [10.1116/6.0000377](https://doi.org/10.1116/6.0000377) | | | |
| Science (AAAS) | [10.1126/science.abb2507](https://doi.org/10.1126/science.abb2507) | | | |

arXiv is checked already. Afterwards: delete the collection's papers (or
keep them), and tick the publishers in #41.
