# Maintaining the GitHub release

Repository: https://github.com/Yeydi-code/portfolio-tracker

## Before publishing an update

1. Run the Python and interface test suites, then build the frontend as described in the main README.
2. Review the files to commit. Keep saved portfolios, downloads, logs, backups, credentials and generated assets out of Git.
3. Run `python scripts/check_release.py` after staging intended source changes.
4. Commit the reviewed changes and push your branch. Check the GitHub Actions result for that commit before describing it as verified.

The MIT notice uses “Portfolio Tracker contributors” as collective attribution. Dependencies retain their own licenses, and the software license does not grant redistribution rights for third-party market data.

## Sharing the project

Use the repository link on a CV or portfolio. The README includes installation instructions, screenshots, an offline walkthrough, and the limitations of each model. No paid deployment is required.

A concise portfolio description:

> Built a local financial research terminal with React and Python, covering portfolio risk, multi-leg options, DCF and bond valuation, historical stock backtesting, modeled covered-call simulation, observed volatility grids, and crypto spot analysis. Added reproducible offline examples, auditable calculations, persistent workspaces, and automated tests.

The project does not claim institutional trading performance or hedge-fund-grade accuracy. Covered-call option prices are modeled; the volatility grid is unfitted; crypto analysis covers spot holdings.
