# PaperLens public beta support

PaperLens is a limited public beta. Supported input is arXiv identifiers and
arXiv URLs. IEEE, DOI, publisher-hosted PDFs, arbitrary uploads, and complete
figure-region understanding are not supported inputs in this release.

## What is retained

During the beta, source PDFs, normalized documents, evidence records, optional
analysis/verification, chat sessions, workspaces, and research runs are
retained until an operator-approved retention policy is applied. Do not upload
private or confidential papers. Operators should back up PostgreSQL and the
source-paper volume together.

## Reporting a problem

Open a GitHub issue using the appropriate template. Do not attach copyrighted
PDFs or provider responses. Include:

- the arXiv identifier and route that failed;
- the approximate UTC time;
- the visible request ID (for serious API errors);
- a short, reproducible description and expected behavior;
- browser and deployment version when relevant.

Remove API keys, cookies, authorization headers, private paper text, and
personal data before sharing logs. The beta does not promise scientific
accuracy: important conclusions must be checked against the original source.
