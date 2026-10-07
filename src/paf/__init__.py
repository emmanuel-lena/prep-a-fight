"""prep-a-fight (paf): analyze top logs and adapt gear and cooldowns to a specific boss fight."""

__version__ = "0.5.9"

from paf import net as _net  # noqa: E402

_net.install()  # every HTTPS call of the app: system certificates + certifi (issue #17)
