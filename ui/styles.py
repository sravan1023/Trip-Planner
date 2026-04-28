from pathlib import Path


APP_CSS = (
    "<style>\n"
    + Path(__file__).with_name("styles.css").read_text(encoding="utf-8")
    + "\n</style>"
)
