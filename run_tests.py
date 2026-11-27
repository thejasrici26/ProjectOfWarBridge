import sys
import unittest


def main():
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print("Unexpected skipped tests:", file=sys.stderr)
        for test, reason in result.skipped:
            print(f"- {test}: {reason}", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
