"""Small controlled fixture; no third-party dependencies."""
import sys


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "human"
    print(f"Hello, {name}. Human time matters.")
