"""Feishu Builder Agent (V2)."""


def main() -> None:
    from .cli import main as cli_main

    cli_main()


__all__ = ["main"]
