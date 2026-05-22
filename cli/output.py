from cli.proxy import sys_proxy as sys, json
from typing import Any, Dict
from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme

# Custom theme for ForcedFocus
FF_THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "highlight": "bold magenta",
        "dim": "grey50",
        "mode.blacklist": "bold red",
        "mode.whitelist": "bold green",
    }
)

_real_console = Console(theme=FF_THEME)
class ConsoleProxy:
    def __getattr__(self, name):
        import sys
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, "console") and ff_cli.console is not self:
                return getattr(ff_cli.console, name)
        return getattr(_real_console, name)

    def __setattr__(self, name, value):
        import sys
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, "console") and ff_cli.console is not self:
                setattr(ff_cli.console, name, value)
                return
        setattr(_real_console, name, value)

    def __delattr__(self, name):
        import sys
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, "console") and ff_cli.console is not self:
                try:
                    delattr(ff_cli.console, name)
                    return
                except AttributeError:
                    pass
        try:
            delattr(_real_console, name)
        except AttributeError:
            pass

console = ConsoleProxy()

class OutputHandler:
    """Handles switching between JSON (agent) and Rich (human) output."""

    def __init__(self, use_human: bool = False, use_agent: bool = False):
        # Explicit flags take precedence
        if use_human:
            self.is_human = True
        elif use_agent:
            self.is_human = False
        else:
            # Default to human if it's a TTY
            self.is_human = sys.stdout.isatty()

        self.is_agent = not self.is_human

    def print_data(self, data: Dict[str, Any], title: str = "ForcedFocus Response"):
        """Print data in the current mode."""
        if self.is_agent:
            print(json.dumps(data, indent=2))
        else:
            self._print_rich(data, title)

    def print_error(self, message: str, code: str = "ERROR", suggestion: str = None):
        """Print error in a structured way."""
        error_data = {
            "error": True,
            "code": code,
            "message": message,
            "suggestion": suggestion,
        }
        if self.is_agent:
            print(json.dumps(error_data, indent=2), file=sys.stderr)
        else:
            console.print(f"[error]✗ {message}[/error]")
            if suggestion:
                console.print(f"[dim]  Suggestion: {suggestion}[/dim]")
        sys.exit(1 if code != "USAGE_ERROR" else 2)

    def _print_rich(self, data: Dict[str, Any], title: str):
        """Internal helper for beautiful rich output."""
        status = data.get("status", "ok")
        msg = data.get("message", "")

        if status == "ok":
            console.print(
                Panel(
                    f"[success]✓[/success] {msg}",
                    title=title,
                    border_style="success",
                    expand=False,
                )
            )
        elif status == "pending":
            console.print(
                Panel(
                    f"[warning]⏱[/warning] {msg}",
                    title=title,
                    border_style="warning",
                    expand=False,
                )
            )
        elif status == "error":
            console.print(
                Panel(
                    f"[error]✗[/error] {msg}",
                    title=title,
                    border_style="error",
                    expand=False,
                )
            )
        else:
            console.print(Panel(f"{msg}", title=title, expand=False))

_real_out = OutputHandler()
class OutputProxy:
    def __getattr__(self, name):
        import sys
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, "out") and ff_cli.out is not self:
                return getattr(ff_cli.out, name)
        return getattr(_real_out, name)

    def __setattr__(self, name, value):
        import sys
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, "out") and ff_cli.out is not self:
                setattr(ff_cli.out, name, value)
                return
        setattr(_real_out, name, value)

    def __delattr__(self, name):
        import sys
        if "forcefocus_cli" in sys.modules:
            ff_cli = sys.modules["forcefocus_cli"]
            if hasattr(ff_cli, "out") and ff_cli.out is not self:
                try:
                    delattr(ff_cli.out, name)
                    return
                except AttributeError:
                    pass
        try:
            delattr(_real_out, name)
        except AttributeError:
            pass

out = OutputProxy()
