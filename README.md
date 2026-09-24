# As-Built ISO Review — Live Status
Static dashboard on GitHub Pages. A scheduled GitHub Action reads the Google Sheet (must be shared
"Anyone with the link → Viewer"), builds `site/data/summary.json`, and redeploys every 3 hours.
Edit `config.json` to add Lot 3 (tab gid) or change status keywords. No secrets are stored in this repo.
