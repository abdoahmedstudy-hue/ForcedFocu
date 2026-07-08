from cli.proxy import os, sys_proxy as sys, getpass, hashlib, json
from rich.panel import Panel
from cli.output import out, console
from cli.client import CONFIG_DIR, KS_HASH_FILE

def cmd_set_key(_args):
    """Set or change the kill-switch passphrase."""
    if os.geteuid() != 0:
        out.print_error(
            "Must run as root to set the kill-switch passphrase.",
            code="PERM_DENIED",
            suggestion="Use: sudo forcefocus set-key",
        )

    console.print(
        Panel(
            "This passphrase is required to unlock an active blocking session.\nIt is stored as a secure PBKDF2-HMAC-SHA256 hash.",
            title="[highlight]Set Kill-Switch Passphrase[/highlight]",
            expand=False,
        )
    )

    try:
        p1 = getpass.getpass("  New Passphrase: ")
        if not p1:
            out.print_error("Passphrase cannot be empty.", code="INVALID_INPUT")
        p2 = getpass.getpass("  Confirm Passphrase: ")
        if p1 != p2:
            out.print_error("Passphrases do not match.", code="MISMATCH")

        # PBKDF2-HMAC-SHA256 — must match daemon's _verify_passphrase()
        salt = os.urandom(16)
        iterations = 100_000  # Must match daemon (forcefocus_daemon.py L1827)
        key_hash = hashlib.pbkdf2_hmac("sha256", p1.encode(), salt, iterations)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {"salt": salt.hex(), "hash": key_hash.hex()}
        temp_path = KS_HASH_FILE.with_suffix(".tmp")
        try:
            with open(temp_path, "w") as f:
                json.dump(data, f)
            os.chmod(temp_path, 0o600)
            
            # Remove any existing immutable flag before replacing
            if KS_HASH_FILE.exists():
                try:
                    import subprocess
                    subprocess.run(["chflags", "nouchg", str(KS_HASH_FILE)], capture_output=True)
                except Exception:
                    pass
                    
            os.replace(temp_path, KS_HASH_FILE)
            
            # Make the new ks_hash immutable to prevent unauthorized modification
            try:
                import subprocess
                subprocess.run(["chflags", "uchg", str(KS_HASH_FILE)], capture_output=True)
            except Exception:
                pass
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            raise
        out.print_data(
            {"status": "ok", "message": "Passphrase set successfully."}, title="Set Key"
        )
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
