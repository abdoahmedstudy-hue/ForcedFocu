from cli.proxy import sys_proxy as sys, subprocess, Path
from cli.output import out

def cmd_web(args):
    """Start or stop the web interface."""
    action = args.action
    if action == "start":
        out.print_data(
            {"status": "ok", "message": "Starting web interface..."}, title="Web UI"
        )
        web_script = Path("/usr/local/bin/forcefocus_web.py")
        if not web_script.exists():
            if "forcefocus_cli" in sys.modules:
                ff_cli = sys.modules["forcefocus_cli"]
                if hasattr(ff_cli, "__file__") and ff_cli.__file__:
                    web_script = Path(ff_cli.__file__).parent / "forcefocus_web.py"
                else:
                    web_script = Path(__file__).resolve().parents[2] / "forcefocus_web.py"
            else:
                web_script = Path(__file__).resolve().parents[2] / "forcefocus_web.py"

        if web_script.exists():
            subprocess.run([sys.executable, str(web_script)])
        else:
            out.print_error("Web server script not found.", code="FILE_NOT_FOUND")
    elif action == "stop":
        out.print_data(
            {"status": "ok", "message": "Stopping web interface..."}, title="Web UI"
        )
        # In a real implementation, we would find and kill the process.
