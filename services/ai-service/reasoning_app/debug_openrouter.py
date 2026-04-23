import os

def debug_openrouter_env() -> None:
    print("OPENROUTER ENV CHECK")
    for key in sorted(os.environ.keys()):
        upper = key.upper()
        if "OPEN" in upper or "ROUTER" in upper:
            print(f"{key}=<redacted>")


if __name__ == "__main__":
    debug_openrouter_env()

