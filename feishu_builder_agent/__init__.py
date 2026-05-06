"""Feishu Builder Agent V3."""


def main() -> None:
    from .cli import main as cli_main

    cli_main()


__all__ = ["main"]
