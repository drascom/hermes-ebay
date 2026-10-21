"""Native Hermes plugin entrypoint."""
try:
    from .hermes_ebay import register
except ImportError:  # Loaded as a top-level module by pytest or older Hermes releases.
    from hermes_ebay import register

__all__ = ["register"]
